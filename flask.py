# -*- coding: utf-8 -*-
"""
    flask
    ~~~~~

    A microframework based on Werkzeug.  It's extensively documented
    and follows best practice patterns.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import with_statement
import os
import sys

from threading import local
from jinja2 import Environment, PackageLoader, FileSystemLoader
from werkzeug import (
    Request as RequestBase,
    Response as ResponseBase,
)
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import create_environ
from werkzeug.utils import cached_property
from werkzeug.local import LocalStack, LocalProxy
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, InternalServerError


# from secure_cookie.cookie import SecureCookie
class SecureCookie:
    def load_cookie(self, *args, **kwargs):
        pass


# utilities we import from Werkzeug and Jinja2 that are unused
# in the module but are exported as public interface.
from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from markupsafe import Markup
from markupsafe import escape
import pkg_resources

pkg_resources.resource_stream


class Request(RequestBase):
    """The request object used by default in flask.  Remembers the
    matched endpoint and view arguments.

    It is what ends up as :class:`~flask.request`.  If you want to replace
    the request object used you can subclass this and set
    :attr:`~flask.Flask.request_class` to your subclass.
    """

    def __init__(self, environ):
        RequestBase.__init__(self, environ)
        self.endpoint = None
        self.view_args = None


class Response(ResponseBase):
    """The response object that is used by default in flask.  Works like the
    response object from Werkzeug but is set to have a HTML mimetype by
    default.  Quite often you don't have to create this object yourself because
    :meth:`~flask.Flask.make_response` will take care of that for you.

    If you want to replace the response object used you can subclass this and
    set :attr:`~flask.Flask.request_class` to your subclass.
    """

    default_mimetype = 'text/html'


class _RequestGlobals(object):
    pass


class _RequestContext(object):
    """The request context contains all request relevant information.  It is
    created at the beginning of the request and pushed to the
    `_request_ctx_stack` and removed at the end of it.  It will create the
    URL adapter and request object for the WSGI environment provided.
    """

    def __init__(self, app, environ):
        self.app = app
        self.url_adapter = app.url_map.bind_to_environ(environ)
        self.request = app.request_class(environ)
        self.session = app.open_session(self.request)
        self.g = _RequestGlobals()
        self.flashes = None

    def __enter__(self):
        _request_ctx_stack.push(self)

    def __exit__(self, exc_type, exc_value, tb):
        # do not pop the request stack if we are in debug mode and an
        # exception happened.  This will allow the debugger to still
        # access the request object in the interactive shell.
        if tb is None or not self.app.debug:
            _request_ctx_stack.pop()


def url_for(endpoint, **values):
    """Generates a URL to the given endpoint with the method provided.

    :param endpoint: the endpoint of the URL (name of the function)
    :param values: the variable arguments of the URL rule
    """
    return _request_ctx_stack.top.url_adapter.build(endpoint, values)


def flash(message):
    """Flashes a message to the next request.  In order to remove the
    flashed message from the session and to display it to the user,
    the template has to call :func:`get_flashed_messages`.

    :param message: the message to be flashed.
    """
    session['_flashes'] = (session.get('_flashes', [])) + [message]


def get_flashed_messages():
    """Pulls all flashed messages from the session and returns them.
    Further calls in the same request to the function will return
    the same messages.
    """
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = session.pop('_flashes', [])
    return flashes


def render_template(template_name, **context):
    """Renders a template from the template folder with the given
    context.

    :param template_name: the name of the template to be rendered
    :param context: the variables that should be available in the
                    context of the template.
    """
    current_app.update_template_context(context)
    return current_app.jinja_env.get_template(template_name).render(context)


def render_template_string(source, **context):
    """Renders a template from the given template source string
    with the given context.

    :param template_name: the sourcecode of the template to be
                          rendered
    :param context: the variables that should be available in the
                    context of the template.
    """
    current_app.update_template_context(context)
    return current_app.jinja_env.from_string(source).render(context)


def _default_template_ctx_processor():
    """Default template context processor.  Injects `request`,
    `session` and `g`.
    """
    reqctx = _request_ctx_stack.top
    return dict(request=reqctx.request, session=reqctx.session, g=reqctx.g)


def _get_package_path(name):
    """Returns the path to a package or cwd if that cannot be found."""
    try:
        return os.path.abspath(os.path.dirname(sys.modules[name].__file__))
    except (KeyError, AttributeError):
        return os.getcwd()


class Flask(object):
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an `__init__.py` file inside) or a standard module (just a `.py` file).

    For more information about resource loading, see :func:`open_resource`.

    Usually you create a :class:`Flask` instance in your main module or
    in the `__init__.py` file of your package like this::

        from flask import Flask
        app = Flask(__name__)
    """

    #: the class that is used for request objects.  See :class:`~flask.request`
    #: for more information.
    request_class = Request

    #: the class that is used for response objects.  See
    #: :class:`~flask.Response` for more information.
    response_class = Response

    #: path for the static files.  If you don't want to use static files
    #: you can set this value to `None` in which case no URL rule is added
    #: and the development server will no longer serve any static files.
    static_path = '/static'

    #: if a secret key is set, cryptographic components can use this to
    #: sign cookies and other things.  Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    secret_key = None

    #: The secure cookie uses this for the name of the session cookie
    session_cookie_name = 'session'

    #: options that are passed directly to the Jinja2 environment
    jinja_options = dict(autoescape=True, extensions=['jinja2.ext.autoescape', 'jinja2.ext.with_'])

    def __init__(self, package_name):
        # 调试标志
        self.debug = False

        # 包名称，一般为 `__name__`
        self.package_name = package_name

        # 应用程序根目录在
        self.root_path = "."  # _get_package_path(self.package_name)

        # 所有已注册视图函数的字典.
        # key 是函数名称.
        # 使用 :meth:`route` 装饰器注册.
        self.view_functions = {}

        # 所有已注册错误处理程序的字典. key 是错误码.
        self.error_handlers = {}

        # 在请求开始时调用的函数列表.
        # 可以处理数据库连接或者登陆.
        # 使用 :meth:`before_request` 装饰器注册
        self.before_request_funcs = []

        # 在请求结束时调用的函数列表.
        # 该函数被传递给当前响应对象，并就地修改或替换它.
        # 使用 :meth:`after_request` 装饰器注册.
        self.after_request_funcs = []

        #: a list of functions that are called without arguments
        #: to populate the template context.  Each returns a dictionary
        #: that the template context is updated with.
        #: To register a function here, use the :meth:`context_processor`
        #: decorator.
        self.template_context_processors = [_default_template_ctx_processor]

        self.url_map = Map()

        if self.static_path is not None:
            self.url_map.add(Rule(self.static_path + '/<filename>', build_only=True, endpoint='static'))
            if pkg_resources is not None:
                target = (self.package_name, 'static')
            else:
                target = os.path.join(self.root_path, 'static')
            # self.wsgi_app = SharedDataMiddleware(self.wsgi_app, {self.static_path: target})

        #: the Jinja2 environment.  It is created from the
        #: :attr:`jinja_options` and the loader that is returned
        #: by the :meth:`create_jinja_loader` function.
        # self.jinja_env = Environment(loader=self.create_jinja_loader(), **self.jinja_options) # TODO
        # self.jinja_env.globals.update(url_for=url_for, get_flashed_messages=get_flashed_messages) # TODO

    def create_jinja_loader(self):
        """Creates the Jinja loader.  By default just a package loader for
        the configured package is returned that looks up templates in the
        `templates` folder.  To add other loaders it's possible to
        override this method.
        """
        if pkg_resources is None:
            return FileSystemLoader(os.path.join(self.root_path, 'templates'))
        return PackageLoader(self.package_name)

    def update_template_context(self, context):
        """Update the template context with some commonly used variables.
        This injects request, session and g into the template context.

        :param context: the context as a dictionary that is updated in place
                        to add extra variables.
        """
        reqctx = _request_ctx_stack.top
        for func in self.template_context_processors:
            context.update(func())

    def run(self, host='localhost', port=5000, **options):
        """主运行函数"""
        from werkzeug.serving import run_simple

        if 'debug' in options:
            self.debug = options.pop('debug')
        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)
        return run_simple(host, port, self, **options)

    def test_client(self):
        """Creates a test client for this application.  For information
        about unit testing head over to :ref:`testing`.
        """
        from werkzeug import Client

        return Client(self, self.response_class, use_cookies=True)

    def open_resource(self, resource):
        """Opens a resource from the application's resource folder.  To see
        how this works, consider the following folder structure::

            /myapplication.py
            /schemal.sql
            /static
                /style.css
            /template
                /layout.html
                /index.html

        If you want to open the `schema.sql` file you would do the
        following::

            with app.open_resource('schema.sql') as f:
                contents = f.read()
                do_something_with(contents)

        :param resource: the name of the resource.  To access resources within
                         subfolders use forward slashes as separator.
        """
        if pkg_resources is None:
            return open(os.path.join(self.root_path, resource), 'rb')
        return pkg_resources.resource_stream(self.package_name, resource)

    def open_session(self, request):
        """Creates or opens a new session.  Default implementation stores all
        session data in a signed cookie.  This requires that the
        :attr:`secret_key` is set.

        :param request: an instance of :attr:`request_class`.
        """
        key = self.secret_key
        if key is not None:
            return SecureCookie.load_cookie(request, self.session_cookie_name, secret_key=key)

    def save_session(self, session, response):
        """Saves the session if it needs updates.  For the default
        implementation, check :meth:`open_session`.

        :param session: the session to be saved (a
                        :class:`~werkzeug.contrib.securecookie.SecureCookie`
                        object)
        :param response: an instance of :attr:`response_class`
        """
        if session is not None:
            session.save_cookie(response, self.session_cookie_name)

    def add_url_rule(self, rule, endpoint, **options):
        """关联一个URL规则.  一般使用 `route`.

        下面示例::

            @app.route('/')
            def index():
                pass

        等价于::

            def index():
                pass
            app.add_url_rule('index', '/')
            app.view_functions['index'] = index
        """
        options['endpoint'] = endpoint
        options.setdefault('methods', ('GET',))
        self.url_map.add(Rule(rule, **options))

    def route(self, rule, **options):
        """注册路由装饰器. Example::

            @app.route('/')
            def index():
                return 'Hello World'
        """

        def decorator(f):
            self.add_url_rule(rule, f.__name__, **options)
            self.view_functions[f.__name__] = f
            return f

        return decorator

    def errorhandler(self, code):
        """注册错误码装饰器.  Example::

            @app.errorhandler(404)
            def page_not_found():
                return 'This page does not exist', 404
        """

        def decorator(f):
            self.error_handlers[code] = f
            return f

        return decorator

    def before_request(self, f):
        """注册一个在每个请求之前运行的函数"""
        self.before_request_funcs.append(f)
        return f

    def after_request(self, f):
        """注册一个在每个请求之后运行的函数"""
        self.after_request_funcs.append(f)
        return f

    def context_processor(self, f):
        """Registers a template context processor function."""
        self.template_context_processors.append(f)
        return f

    def match_request(self):
        """Matches the current request against the URL map and also
        stores the endpoint and view arguments on the request object
        is successful, otherwise the exception is stored.
        """
        rv = _request_ctx_stack.top.url_adapter.match()
        request.endpoint, request.view_args = rv
        return rv

    def dispatch_request(self):
        """Does the request dispatching.  Matches the URL and returns the
        return value of the view or error handler.  This does not have to
        be a response object.  In order to convert the return value to a
        proper response object, call :func:`make_response`.
        """
        try:
            endpoint, values = self.match_request()
            return self.view_functions[endpoint](**values)
        except HTTPException as e:
            handler = self.error_handlers.get(e.code)
            if handler is None:
                return e
            return handler(e)
        except Exception as e:
            handler = self.error_handlers.get(500)
            if self.debug or handler is None:
                raise
            return handler(e)

    def make_response(self, rv):
        """Converts the return value from a view function to a real
        response object that is an instance of :attr:`response_class`.

        The following types are allowd for `rv`:

        ======================= ===========================================
        :attr:`response_class`  the object is returned unchanged
        :class:`str`            a response object is created with the
                                string as body
        :class:`unicode`        a response object is created with the
                                string encoded to utf-8 as body
        :class:`tuple`          the response object is created with the
                                contents of the tuple as arguments
        a WSGI function         the function is called as WSGI application
                                and buffered as response object
        ======================= ===========================================

        :param rv: the return value from the view function
        """
        if isinstance(rv, self.response_class):
            return rv
        if isinstance(rv, str):
            return self.response_class(rv)
        if isinstance(rv, tuple):
            return self.response_class(*rv)
        return self.response_class.force_type(rv, request.environ)

    def preprocess_request(self):
        """Called before the actual request dispatching and will
        call every as :meth:`before_request` decorated function.
        If any of these function returns a value it's handled as
        if it was the return value from the view and further
        request handling is stopped.
        """
        for func in self.before_request_funcs:
            rv = func()
            if rv is not None:
                return rv

    def process_response(self, response):
        """Can be overridden in order to modify the response object
        before it's sent to the WSGI server.  By default this will
        call all the :meth:`after_request` decorated functions.

        :param response: a :attr:`response_class` object.
        :return: a new response object or the same, has to be an
                 instance of :attr:`response_class`.
        """
        session = _request_ctx_stack.top.session
        if session is not None:
            self.save_session(session, response)
        for handler in self.after_request_funcs:
            response = handler(response)
        return response

    def wsgi_app(self, environ, start_response):
        """The actual WSGI application.  This is not implemented in
        `__call__` so that middlewares can be applied:

            app.wsgi_app = MyMiddleware(app.wsgi_app)

        :param environ: a WSGI environment
        :param start_response: a callable accepting a status code,
                               a list of headers and an optional
                               exception context to start the response
        """
        with self.request_context(environ):
            rv = self.preprocess_request()
            if rv is None:
                rv = self.dispatch_request()
            response = self.make_response(rv)
            response = self.process_response(response)
            return response(environ, start_response)

    def request_context(self, environ):
        """Creates a request context from the given environment and binds
        it to the current context.  This must be used in combination with
        the `with` statement because the request is only bound to the
        current context for the duration of the `with` block.

        Example usage::

            with app.request_context(environ):
                do_something_with(request)

        :params environ: a WSGI environment
        """
        return _RequestContext(self, environ)

    def test_request_context(self, *args, **kwargs):
        """Creates a WSGI environment from the given values (see
        :func:`werkzeug.create_environ` for more information, this
        function accepts the same arguments).
        """
        return self.request_context(create_environ(*args, **kwargs))

    def __call__(self, environ, start_response):
        """Shortcut for :attr:`wsgi_app`"""
        return self.wsgi_app(environ, start_response)


# context locals
_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)
session = LocalProxy(lambda: _request_ctx_stack.top.session)
g = LocalProxy(lambda: _request_ctx_stack.top.g)
