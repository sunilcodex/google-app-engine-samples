#!/usr/bin/python
#
# Copyright 2008 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
A sample OpenID consumer app for Google App Engine. Allows users to log into
other OpenID providers, then displays their OpenID login. Also stores and
displays the most recent logins.

Part of http://code.google.com/p/google-app-engine-samples/.

For more about OpenID, see:
  http://openid.net/
  http://openid.net/about.bml

Uses JanRain's Python OpenID library, version 2.1.1, licensed under the
Apache Software License 2.0:
  http://openidenabled.com/python-openid/

The JanRain library includes a reference OpenID provider that can be used to
test this consumer. After starting the dev_appserver with this app, unpack the
JanRain library and run these commands from its root directory:

  setenv PYTHONPATH .
  python ./examples/server.py -s localhost

Then go to http://localhost:8080/ in your browser, type in
http://localhost:8000/test as your OpenID identifier, and click Verify.
"""

import cgi
import Cookie
import datetime
import logging
import os
import pickle
import pprint
import sys
import traceback
import urlparse
import wsgiref.handlers

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

from openid import fetchers
from openid.consumer.consumer import Consumer
from openid.consumer import discover
import fetcher
import store

# Set to True if stack traces should be shown in the browser, etc.
_DEBUG = False


class Login(db.Model):
  """A completed OpenID login."""
  result = db.StringProperty(choices=('confirmed', 'declined'))
  openid = db.LinkProperty()
  provider = db.LinkProperty()
  time = db.DateTimeProperty(auto_now_add=True)


class Session(db.Expando):
  """An in-progress OpenID login."""
  pass


class Handler(webapp.RequestHandler):
  """A base handler class with a couple OpenID-specific utilities."""
  consumer = None
  session = None

  def get_consumer(self):
    """Returns a Consumer instance.
    """
    if not self.consumer:
      fetchers.setDefaultFetcher(fetcher.UrlfetchFetcher())
      session = self.get_session()
      self.consumer = Consumer(vars(session), store.DatastoreStore())

    return self.consumer

  def args_to_dict(self):
    """Converts the URL and POST parameters to a singly-valued dictionary.

    Returns:
      dict with the URL and POST body parameters
    """
    req = self.request
    return dict([(arg, req.get(arg)) for arg in req.arguments()])

  def get_session(self):
    """Gets the current session.
    """
    if not self.session:
      id = self.request.get('session_id')
      if id:
        try:
          self.session = db.get(db.Key.from_path('Session', int(id)))
          assert self.session
        except (AssertionError, db.Error), e:
          self.report_error(str('Invalid session id: %d' % id))
      else:
        self.session = Session()

    return self.session
    

#   def has_cookie(self):
#     """Returns True if we "remember" the user, False otherwise.

#     Determines whether the user has used OpenID before and asked us to
#     remember them - ie, if the user agent provided an 'openid_remembered'
#     cookie.

#     Returns:
#       True if we remember the user, False otherwise.
#     """
#     cookies = os.environ.get('HTTP_COOKIE', None)
#     if cookies:
#       morsel = Cookie.BaseCookie(cookies).get('openid_remembered')
#       if morsel and morsel.value == 'yes':
#         return True

#     return False

#   def get_openid_request(self):
#     """Creates and OpenIDRequest for this request, if appropriate.

#     If this request is not an OpenID request, returns None. If an error occurs
#     while parsing the arguments, returns False and shows the error page.

#     Return:
#       An OpenIDRequest, if this user request is an OpenID request. Otherwise
#       False.
#     """
#     try:
#       oidrequest = oidconsumer.decodeRequest(self.args_to_dict())
#       logging.debug('OpenID request: %s' % oidrequest)
#       return oidrequest
#     except:
#       trace = ''.join(traceback.format_exception(*sys.exc_info()))
#       self.ReportError('Error parsing OpenID request:\n%s' % trace)
#       return False

#   def respond(self, oidresponse):
#     """Send an OpenID response.

#     Args:
#       oidresponse: OpenIDResponse
#       The response to send, usually created by OpenIDRequest.answer().
#     """
#     logging.warning('respond: oidresponse.request.mode ' + oidresponse.request.mode)

#     logging.debug('Using response: %s' % oidresponse)
#     encoded_response = oidconsumer.encodeResponse(oidresponse)

#     # update() would be nice, but wsgiref.headers.Headers doesn't implement it
#     for header, value in encoded_response.headers.items():
#       self.response.headers[header] = str(value)

#     if encoded_response.code in (301, 302):
#       self.redirect(self.response.headers['location'])
#     else:
#       self.response.set_status(encoded_response.code)

#     if encoded_response.body:
#       logging.debug('Sending response body: %s' % encoded_response.body)
#       self.response.out.write(encoded_response.body)
#     else:
#       self.response.out.write('')

  def render(self, template_name, extra_values={}):
    """render the given template, including the extra (optional) values.

    Args:
      template_name: string
      The template to render.

      extra_values: dict
      Template values to provide to the template.
    """
    values = {
      'request': self.request,
      'debug': self.request.get('deb'),
    }
    values.update(extra_values)
    cwd = os.path.dirname(__file__)
    path = os.path.join(cwd, 'templates', template_name + '.html')
    logging.debug(path)
    self.response.out.write(template.render(path, values, debug=_DEBUG))

  def report_error(self, message):
    """Shows an error HTML page.

    Args:
      message: string
      A detailed error message.
    """
    args = pprint.pformat(self.args_to_dict())
    self.render('error', vars())
    logging.error(message)

  def show_front_page(self):
    """Do an internal (non-302) redirect to the front page.

    Preserves the user agent's requested URL.
    """
    front_page = FrontPage()
    front_page.request = self.request
    front_page.response = self.response
    front_page.get()


class FrontPage(Handler):
  """Show the default OpenID page, with the last 10 logins for this user."""
  def get(self):
    logins = []
    self.render('index', vars())


class LoginHandler(Handler):
  """Handles a POST response to the OpenID login form."""

  def post(self):
    """Handles login requests."""
    openid_url = self.request.get('openid')
    if not openid_url:
      self.show_front_page()

    try:
      auth_request = self.get_consumer().begin(openid_url)
    except discover.DiscoveryFailure, e:
      self.report_error(str(e))

    session = Session()
    session.put()

    parts = urlparse.urlparse(self.request.uri)
    parts[2] = 'finish'
    parts[4] = 'session_id=%d' % session.key().id()
    parts[5] = ''
    return_to = urlparse.urlunparse(parts)
    realm = urlparse.urlunparse(parts[0:1] + [''] * 4)

    logging.info('redirecting to %s' % auth_request.redirectURL(realm, return_to))
    self.redirect(auth_request.redirectURL(realm, return_to))


class FinishLoginHandler(Handler):
  """Handle a redirect from the provider."""
  def post(self):
    args = self.args_to_dict()
    response = self.get_consumer().complete(args, self.request.uri)
    self.response.write('\r\n\r\n%s\r\n\r\n' % self.response.status)

    if args.has_key('yes'):
      logging.debug('Confirming identity to %s' % oidrequest.trust_root)
      if args.get('remember', '') == 'yes':
        logging.info('Setting cookie to remember openid login for two weeks')

        expires = datetime.datetime.now() + datetime.timedelta(weeks=2)
        expires_rfc822 = expires.strftime('%a, %d %b %Y %H:%M:%S +0000')
        self.response.headers.add_header(
          'Set-Cookie', 'openid_remembered=yes; expires=%s' % expires_rfc822)

      self.store_login(oidrequest, 'confirmed')
      self.respond(oidrequest.answer(True))

    elif args.has_key('no'):
      logging.debug('Login denied, sending cancel to %s' %
                    oidrequest.trust_root)
      self.store_login(oidrequest, 'declined')
      return self.respond(oidrequest.answer(False))

    else:
      self.report_error('Bad login request.')


# Map URLs to our RequestHandler classes above
_URLS = [
  ('/', FrontPage),
  ('/login', LoginHandler),
  ('/finish', FinishLoginHandler),
]

def main(argv):
  application = webapp.WSGIApplication(_URLS, debug=_DEBUG)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
  main(sys.argv)
 