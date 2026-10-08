from django.apps import AppConfig

class ListaConfig(AppConfig):
    """
    Configuration for an application named 'lista' in Django.
    This class inherits from AppConfig and performs the
    configuration of the application.

    Attributes:
        default_auto_field (str): The default field type for models' primary keys.
        The primary key will be created as a BigAutoField.
        name (str): The name of the application. This attribute specifies
        the module or folder name of the app.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'lista'

    def ready(self):
        """
        A method that is called when the application is loaded.
        Custom code can be added here to run when the application is ready
        (e.g., automatic synchronization, various settings, etc.).

        Description:
            Typically, this method does not need to be modified unless
            special configuration is required when the application is ready.
        """
