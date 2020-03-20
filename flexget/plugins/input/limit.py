import itertools

from loguru import logger

from flexget import plugin
from flexget.event import EventType, event

logger = logger.bind(name='limit')


class PluginLimit:
    """
    Limits the number of entries an input plugin can produce.
    """

    schema = {
        'type': 'object',
        'properties': {
            'amount': {'type': 'integer', 'minimum': -1},
            'from': {
                'allOf': [
                    {'$ref': '/schema/plugins?phase=input'},
                    {
                        'maxProperties': 1,
                        'error_maxProperties': 'Plugin options within limit plugin must be indented 2 more spaces than '
                        'the first letter of the plugin name.',
                        'minProperties': 1,
                    },
                ]
            },
        },
        'required': ['amount', 'from'],
        'additionalProperties': False,
    }

    def on_task_input(self, task, config):
        for input_name, input_config in config['from'].items():
            input = plugin.get_plugin_by_name(input_name)
            method = input.phase_handlers['input']
            try:
                result = method(task, input_config)
            except plugin.PluginError as e:
                logger.warning('Error during input plugin {}: {}', input_name, e)
                continue
            # A 0 or -1 limit means don't limit.
            if config['amount'] < 1:
                return result
            return itertools.islice(result, config['amount'])


@event(EventType.plugin__register)
def register_plugin():
    plugin.register(PluginLimit, 'limit', api_ver=2)
