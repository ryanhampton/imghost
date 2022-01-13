import configparser
from functools import wraps
import imghdr
import json
import os
import random
import secrets
from urllib.parse import urlparse

from flask import Flask, jsonify, request, redirect, \
    render_template, send_from_directory, url_for
import rollbar

# load ini
conf = configparser.ConfigParser()
conf.read('/home/ryan/imghost/config.ini')
key = conf.get('settings', 'key')
rollbar_token = conf.get('settings', 'rollbar_token')
UPLOAD_FOLDER = conf.get('settings', 'upload_dir')
print(conf.get('allowed_exts', 'image'))
ALLOWED_EXTENSIONS = json.loads(conf.get('allowed_exts', 'image'))

# flask config
app = Flask(__name__.split('.')[0])
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 20 * 1000 * 1000
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.add_url_rule("/uploads/<name>", endpoint="download_file", build_only=True)

# initialize rollbar
rollbar.init(rollbar_token, environment='development')

def require_key(view_func):
    """ Decorator for endpoints locked behind the API key """
    @wraps(view_func)
    def decorated_func(*args, **kwargs):
        auth = request.headers.get("X-Api-Key")
        if auth and auth == key:
            return view_func(*args, **kwargs)
        else:
            rollbar.report_message('No API key supplied', 'info')
            return {
                    'success': False,
                    'error': "API key required"
            }, 401
    return decorated_func


def validate_image(stream):
    """ Checks the header of the uploaded file to make sure it's a proper image """
    header = stream.read(512)
    stream.seek(0)
    format = imghdr.what(None, header)
    if not format:
        return None
    return f'.{format}' if format != 'jpeg' else '.jpg'


def rename_image(extension):
    """ Renames the image file to be random/safe """
    return f"{secrets.token_urlsafe(5)}{extension}"


def get_hostname(req):
    """ Returns the base hostname of the running server based upon the Request object """
    return urlparse(req.base_url).hostname


@app.route('/', methods=['POST'])
@require_key
def upload_file():
    """ Endpoint for uploading an image to the image host """
    if request.method == 'POST':
        if 'file' not in request.files:
            rollbar.report_message('File not included with POST request', 'warning')
            return {
                    'success': False,
                    'error': "You didn't upload a file"
            },400

        file = request.files['file']

        if file.filename == '':
            rollbar.report_message('Filename blank in POST request', 'warning')
            return {
                    'success': False,
                    'error': "Blank filename"
            },400

        file_ext = os.path.splitext(file.filename)[1].lower()

        if not file_ext in ALLOWED_EXTENSIONS:
            rollbar.report_message('Unsupported file type in POST request', 'warning')
            return {
                    'success': False,
                    'error': "That type of file isn't supported."
            },400
        
        if file and file_ext in ALLOWED_EXTENSIONS:
            if file_ext == validate_image(file.stream):
                filename = rename_image(file_ext)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                return {
                        'success': True,
                        'url': url_for('link_file', name=filename, _external=True)
                }, 200
            else:
                rollbar.report_message('File did not appear to be an image, despite filename', 'warning')
                return {
                        'success': False,
                        'error': "Sorry, this file looks sketchy."
                },400


@app.route('/uploads/<name>')
def download_file(name):
    """ Endpoint for serving the image file in a template or otherwise """
    return send_from_directory(app.config["UPLOAD_FOLDER"], name)


@app.route('/i/<name>')
def link_file(name):
    """ Endpoint for the 'wrapped' uploaded file for embedding or linking """
    if name in os.listdir(UPLOAD_FOLDER):
        return render_template('image.html', 
                                name=name,
                                hostname=get_hostname(request),
                                img_url=url_for('download_file', name=name, _external=True),
                                this_url=url_for('link_file', name=name, _external=True))
    else:
        return "nope!", 404


if __name__ == '__main__':
    app.run()
