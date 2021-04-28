import json
import math
import numpy as np
import os
import torch

from datasets import tqdm
from transformers import AutoTokenizer
from typing import Dict, List

from thermostat.data import get_local_explanations
from thermostat.utils import detach_to_list, read_path


class RGB:
    def __init__(self, red, green, blue, score):
        self.red = red
        self.green = green
        self.blue = blue
        self.score = round(score, ndigits=3) if score is not None else score

    def __str__(self):
        return 'rgb({},{},{})'.format(self.red, self.green, self.blue)


class Sequence:
    def __init__(self, words, scores):
        assert (len(words) == len(scores))
        self.words = words
        self.scores = scores
        self.size = len(words)

    def words_rgb(self, gamma=1.0, token_pad=None, position_pad='right'):
        rgbs = list(map(lambda tup: self.rgb(word=tup[0], score=tup[1], gamma=gamma), zip(self.words, self.scores)))
        if token_pad is not None:
            if token_pad in self.words:
                if position_pad == 'right':
                    return zip(self.words[:self.words.index(token_pad)], rgbs)
                elif position_pad == 'left':
                    first_token_index = list(reversed(self.words)).index(token_pad)
                    return zip(self.words[-first_token_index:], rgbs[-first_token_index:])
                else:
                    return NotImplementedError
        return zip(self.words, rgbs)

    def compute_length_without_pad_tokens(self, special_tokens: List[str]):
        counter = 0
        for word in self.words:
            if word not in special_tokens:
                counter = counter + 1
        return counter

    @staticmethod
    def gamma_correction(score, gamma):
        return np.sign(score) * np.power(np.abs(score), gamma)

    def rgb(self, word, score, gamma, threshold=0):
        assert not math.isnan(score), 'Score of word {} is NaN'.format(word)
        score = self.gamma_correction(score, gamma)
        if score >= threshold:
            r = str(int(255))
            g = str(int(255 * (1 - score)))
            b = str(int(255 * (1 - score)))
        else:
            b = str(int(255))
            r = str(int(255 * (1 + score)))
            g = str(int(255 * (1 + score)))
        return RGB(r, g, b, score)


def token_to_html(token, rgb):
    return f"<span style=\"background-color: {rgb}\"> {token.replace('<', '').replace('>', '')} </span>"


def summarize(summary: Dict):
    res = "<h4>"
    for k, v in summary.items():
        res += f"{k}: {summary[k]} <br/>"
    res += "</h4>"
    return res


def append_heatmap(tokens, scores, latex, gamma, caption, pad_token, formatting="colorbox", truncate_pad=True):
    """
    Produce a heatmap for LaTeX
    Format options: colorbox, text"""
    if gamma != 1:
        raise NotImplementedError
    latex += "\n\\begin{figure}[!htb]"
    for token, score in zip(tokens, scores):
        if token == pad_token and truncate_pad:
            continue
        color = "blue"
        if score >= 0:
            color = "red"
        latex += f"\\{formatting}" + "{" + f"{color}!{abs(score) * 100}" + "}" + "{" + token + "}"
    latex += "\\caption{" + f"{caption}" + "}"
    latex += "\\end{figure}\n"
    return latex


def run_visualize(config: Dict, logger):
    logger.info("(Progress) Generating visualizations")
    logger.info(f"(Config) Received config \n{json.dumps(config, indent=2)}")
    tokenizer = AutoTokenizer.from_pretrained(config['model']['tokenizer']['name'])
    visualization_config = config['visualization']

    dataset = get_local_explanations(config=visualization_config)
    str_dataset_name = f'{config["dataset"]["name"]} ({config["dataset"]["split"]})'

    file_out = open(read_path(config['path_html']), 'w+')

    for idx_instance in tqdm(range(len(dataset))):
        html = f"<html><h3>"
        html += f"<h2>Instance: {idx_instance} | Dataset: {str_dataset_name} |" \
                f" Model: {config['model']['name']}"
        html += '</h3><div style=\"border:3px solid #000;\">'

        html += "<div>"

        instance = dataset[idx_instance]
        tokens = [tokenizer.decode(token_ids=token_id) for token_id in instance['input_ids']]
        atts = detach_to_list(instance['attributions'])
        if visualization_config['normalize']:
            max_abs_score = max(max(atts), abs(min(atts)))
            atts = [(score / max_abs_score) for score in atts]
        sequence = Sequence(words=tokens, scores=atts)
        words_rgb = sequence.words_rgb(token_pad=tokenizer.pad_token,
                                       position_pad=tokenizer.padding_side,
                                       gamma=visualization_config['gamma'])

        summary = {}
        number_of_non_special_tokens = sequence.compute_length_without_pad_tokens(
            special_tokens=tokenizer.all_special_tokens)
        summary['Non-special tokens'] = number_of_non_special_tokens

        label_names = dataset['label_names'][0]
        if 'labels' in instance:
            label = detach_to_list(instance['labels'])
            summary['True Label Index'] = str(label)
            summary['True Label'] = str(label_names[label])
        if 'predictions' in instance:
            summary['Logits'] = detach_to_list(instance['predictions'])
            preds_max_detached = detach_to_list(torch.argmax(instance['predictions']))
            summary['Predicted Label'] = str(label_names[preds_max_detached])
        html += summarize(summary)

        for word, rgb in words_rgb:  # brackets to reuse iterator
            html += token_to_html(word, rgb)
        html += "</br></br>"
        html += "</div>"
        html += "</div></br></br></br></html>"
        file_out.write(html + os.linesep)
