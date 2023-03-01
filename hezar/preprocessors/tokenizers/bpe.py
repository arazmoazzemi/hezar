import os
from dataclasses import dataclass
from typing import List

from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer as HFTokenizer
from tokenizers import models, decoders, trainers, pre_tokenizers

from .tokenizer import Tokenizer, TokenizerConfig, TokenizerTrainConfig
from ...constants import DEFAULT_TOKENIZER_FILE, DEFAULT_TOKENIZER_CONFIG_FILE
from ...registry import register_preprocessor
from ...utils.hub_utils import resolve_pretrained_path


@dataclass
class BPETrainConfig(TokenizerTrainConfig):
    name: str = "bpe_tokenizer"
    vocab_size: int = 30000
    min_frequency: int = 2
    limit_alphabet: int = 1000
    initial_alphabet = []
    show_progress: bool = True


@dataclass
class BPEConfig(TokenizerConfig):
    name: str = "bpe_tokenizer"
    truncation_strategy: str = "no_truncation"
    padding_strategy: str = "no_padding"
    special_tokens = ["<s>", "<pad>", "</s>", "<unk>", "<mask>",
                      "<|endoftext|>", "<|startoftext|>", "<nl>", "<hs>",
                      "<sep>", "<cls>"]
    unk_token: str = None
    pad_token_id = 0
    pad_token = "<pad>"
    dropout: float = None
    continuing_subword_prefix: str = ""
    end_of_word_suffix: str = ""
    fuse_unk: bool = False
    train_config: BPETrainConfig = BPETrainConfig()


@register_preprocessor("bpe_tokenizer", config_class=BPEConfig)
class BPETokenizer(Tokenizer):
    """
    A standard Byte-level BPE tokenizer using 🤗HuggingFace Tokenizers

    Args:
        config: Preprocessor config for the tokenizer
        kwargs: Extra/manual config parameters
    """

    tokenizer_filename = DEFAULT_TOKENIZER_FILE
    tokenizer_config_filename = DEFAULT_TOKENIZER_CONFIG_FILE
    token_ids_name = "token_ids"

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def build(self):
        pretrained_path = self.config.pop("pretrained_path")
        if pretrained_path:
            if not os.path.isdir(pretrained_path):
                path = resolve_pretrained_path(pretrained_path)
                tokenizer_path = hf_hub_download(
                    path,
                    filename=self.tokenizer_filename,
                    subfolder=self.preprocessor_subfolder,
                )

            else:
                tokenizer_path = os.path.join(
                    pretrained_path,
                    self.preprocessor_subfolder,
                    self.tokenizer_filename,
                )
            tokenizer = HFTokenizer.from_file(tokenizer_path)
        else:
            tokenizer = HFTokenizer(models.BPE(
                dropout=self.config.dropout,
                unk_token=self.config.unk_token,
                continuing_subword_prefix=self.config.continuing_subword_prefix,
                end_of_word_suffix=self.config.end_of_word_suffix,
                fuse_unk=self.config.fuse_unk,
            ))
            tokenizer.add_special_tokens(self.config.special_tokens)
            tokenizer.decoder = decoders.ByteLevel()  # noqa

        return tokenizer

    def train(self, files: List[str], config: BPETrainConfig):
        """Train the model using the given files"""

        trainer = trainers.BpeTrainer(
            vocab_size=config.vocab_size,  # noqa
            min_frequency=config.min_frequency,  # noqa
            show_progress=config.show_progress,  # noqa
            special_tokens=self.config.special_tokens,  # noqa
            initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),  # noqa
        )
        if isinstance(files, str):
            files = [files]
        self._tokenizer.train(files, trainer=trainer)

    def train_from_iterator(self, dataset: List[str], config: BPETrainConfig):
        """Train the model using the given files"""

        trainer = trainers.BpeTrainer(
            vocab_size=config.vocab_size,  # noqa
            min_frequency=config.min_frequency,  # noqa
            show_progress=config.show_progress,  # noqa
            special_tokens=self.config.special_tokens,  # noqa
            initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),  # noqa
        )
        self._tokenizer.train_from_iterator(dataset, trainer=trainer, length=len(dataset))