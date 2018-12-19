from flask import Flask, Blueprint, jsonify, request, make_response
from functools import wraps
import jwt
import api.settings as settings


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('token')

        if not token:
            return jsonify({'message' : 'Token is missing!'})

        try:
            data = jwt.decode(token, settings.APP_AUTH_KEY)
        except:
            return jsonify({'message' : 'Token is invalid!'})

        return f(*args, **kwargs)

    return decorated