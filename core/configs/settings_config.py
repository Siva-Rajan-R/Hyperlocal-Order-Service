from hyperlocal_platform.core.utils.settings_initializer import init_settings
from ..settings import OrdersSettings
from ..constants import ENV_PREFIX,SERVICE_NAME
from dotenv import load_dotenv
load_dotenv()


SETTINGS:OrdersSettings=init_settings(settings=OrdersSettings,service_name=SERVICE_NAME,env_prefix=ENV_PREFIX)