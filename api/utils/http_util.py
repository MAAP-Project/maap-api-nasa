from flask_api import status

def custom_response(msg, code=status.HTTP_200_OK):
    return {
        'code': code,
        'message': msg
    }, code

def err_response(msg, code=status.HTTP_400_BAD_REQUEST):
    return custom_response(msg, code)