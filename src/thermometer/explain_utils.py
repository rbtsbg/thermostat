
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from typing import Dict, Callable

from thermometer.train import load_checkpoint
from thermometer.utils import read_path, Configurable


class Explainer(Configurable):

    def validate_config(self, config: Dict) -> bool:
        raise NotImplementedError

    def from_config(cls, config: Dict):
        raise NotImplementedError

    def explain(self, batch):
        raise NotImplementedError

    def to(self, device):
        raise NotImplementedError


class ExplainerCaptum(Explainer):
    available_models = ['bert-base-cased', 'xlnet-base-cased']

    def __init__(self):
        super().__init__()

    @staticmethod
    def get_inputs_and_additional_args(name_model: str, batch):
        assert name_model in ExplainerCaptum.available_models, f'Unkown model:  {name_model}'
        if name_model == 'bert-base-cased' or name_model == 'xlnet-base-cased':
            assert 'input_ids' in batch, f'Input ids expected for {name_model} but not found.'
            assert 'attention_mask' in batch, f'Attention mask expected for {name_model} but not found.'
            assert 'token_type_ids' in batch, f'Token type ids expected for model {name_model} but not found.'
            input_ids = batch['input_ids']
            additional_forward_args = (batch['attention_mask'], batch['token_type_ids'])
            return input_ids, additional_forward_args
        else:
            raise NotImplementedError

    @staticmethod
    def get_forward_func(name_model: str, model):
        assert name_model in ExplainerCaptum.available_models, f'Unkown model:  {name_model}'

        def bert_forward(input_ids, attention_mask, token_type_ids):
            input_model = {
                'input_ids': input_ids.long(),
                'attention_mask': attention_mask.long(),
                'token_type_ids': token_type_ids.long(),
            }
            output_model = model(**input_model)[0]
            return output_model

        if name_model == 'bert-base-cased' or name_model == 'xlnet-base-cased':
            return bert_forward
        else:  # when adding a model, also update ExplainerCaptum.available_models
            raise NotImplementedError(f'Unknown model {name_model}')

    def validate_config(self, config: Dict) -> bool:
        raise NotImplementedError

    def from_config(cls, config: Dict):
        raise NotImplementedError

    def explain(self, input):
        raise NotImplementedError


class ExplainerAutoModelInitializer(ExplainerCaptum):  # todo check if this is a mixin rather

    def __init__(self):
        super().__init__()
        self.name_model: str = None
        self.model: AutoModelForSequenceClassification = None
        self.path_model: str = None
        self.forward_func: Callable = None
        self.pad_token_id = None
        self.explainer = None
        self.device = None

    def validate_config(self, config: Dict) -> bool:
        assert 'name_model' in config, f'Provide the name of the model to explain. Available models: ' \
                                       f'{ExplainerCaptum.available_models}'
        assert 'path_model' in config, f'Provide a path to the model which should be explained.'
        # needed to deal w/ legacy code:
        assert 'mode_load' in config, f'Should the model be loaded using the ignite framework or huggingface?'
        assert 'num_labels' in config, f'Provide the number of labels.'
        return True

    @classmethod
    def from_config(cls, config):
        res = cls()
        res.validate_config(config)

        # model
        res.name_model = config['name_model']
        res.path_model = read_path(config['path_model'])
        res.mode_load = config['mode_load']
        if res.mode_load == 'huggingface':
            res.model = AutoModelForSequenceClassification.from_pretrained(res.path_model,
                                                                           num_labels=config['num_labels'])
        elif res.mode_load == 'ignite':
            # todo: num_labels hard coded for xlnet
            res.model = AutoModelForSequenceClassification.from_pretrained(res.name_model,
                                                                           num_labels=config['num_labels'])
            load_checkpoint(res.path_model, res.model)
        else:
            raise NotImplementedError
        res.forward_func = res.get_forward_func(name_model=res.name_model, model=res.model)
        res.pad_token_id = AutoTokenizer.from_pretrained(res.name_model).pad_token_id
        return res

    def to(self, device):
        self.device = device
        self.model.to(self.device)

    def get_baseline(self, batch):
        if self.pad_token_id == 0:
            # all non-special token ids are replaced by 0, the pad id
            baseline = batch['input_ids'] * batch['special_tokens_mask']
            return baseline
        else:
            baseline = batch['input_ids'] * batch['special_tokens_mask']  # all input ids now 0
            # add pad_id everywhere,
            # substract again where special tokens are, leaves non special tokens with pad id
            # and conserves original pad ids
            baseline = (baseline + self.pad_token_id) - (batch['special_tokens_mask'] * self.pad_token_id)
            return baseline

    def explain(self, input):
        raise NotImplementedError