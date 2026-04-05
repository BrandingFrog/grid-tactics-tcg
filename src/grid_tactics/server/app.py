"""Flask application factory with Socket.IO setup."""
from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()


def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application.

    Args:
        testing: If True, enables testing mode.

    Returns:
        Configured Flask app with SocketIO initialized.
    """
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-key"
    app.config["TESTING"] = testing

    socketio.init_app(
        app,
        async_mode="threading",
        cors_allowed_origins="*",
    )
    return app
