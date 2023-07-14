"""
Configs are at the core of Hezar. All core modules like `Model`, `Preprocessor`, `Trainer`, etc. take their parameters
as a config container which is an instance of `Config` or its derivatives. A `Config` is a Python dataclass with
auxiliary methods for loading, saving, uploading to the hub and etc.

Examples:
    >>> from hezar import ModelConfig
    >>> config = ModelConfig.load("hezarai/bert-base-fa")

    >>> from hezar import BertLMConfig
    >>> bert_config = BertLMConfig(vocab_size=50000, hidden_size=768)
    >>> bert_config.save("saved/bert")
    >>> bert_config.push_to_hub("hezarai/bert-custom")
"""
import os
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Union

import torch
from huggingface_hub import create_repo, hf_hub_download, upload_file
from omegaconf import DictConfig, OmegaConf

from .utils.common_utils import snake_case
from .constants import DEFAULT_MODEL_CONFIG_FILE, HEZAR_CACHE_DIR, ConfigType, TaskType
from .utils import get_logger, get_module_config_class

__all__ = [
    "Config",
    "ModelConfig",
    "PreprocessorConfig",
    "TrainerConfig",
    "DatasetConfig",
    "EmbeddingConfig",
    "CriterionConfig",
    "OptimizerConfig",
    "LRSchedulerConfig",
    "MetricConfig",
]

logger = get_logger(__name__)

CONFIG_TYPES_MAPPING = {
    "Config": ConfigType.BASE,
    "ModelConfig": ConfigType.MODEL,
    "PreprocessorConfig": ConfigType.PREPROCESSOR,
    "TrainerConfig": ConfigType.TRAINER,
    "DatasetConfig": ConfigType.DATASET,
    "EmbeddingConfig": ConfigType.EMBEDDING,
    "CriterionConfig": ConfigType.CRITERION,
    "OptimizerConfig": ConfigType.OPTIMIZER,
    "LRSchedulerConfig": ConfigType.LR_SCHEDULER,
    "MetricConfig": ConfigType.METRIC,
}


@dataclass
class Config:
    """
    Base class for all configs in Hezar.

    All configs are simple dataclasses that have some customized functionalities to manage their attributes. There are
    also some Hezar specific methods: `load`, `save` and `push_to_hub`.

    """
    @property
    def name(self) -> str:
        """
        if name is empty, then the base Config class is called. Otherwise, the name of the class is returned in snake
        case.
        """
        name = snake_case(self.__class__.__name__.replace("Config", ""))
        name = name or "base"
        return name

    @property
    def config_type(self) -> ConfigType:
        """
        Every config must have a `config_type` attribute that specifies config type e.g, model, dataset, etc.

        Returns:
            A ConfigType type or a string for a custom config
        """
        parent_class = self.__class__.__mro__[1].__name__
        config_type = CONFIG_TYPES_MAPPING[parent_class]
        if config_type == ConfigType.BASE and self.__class__.__name__ not in CONFIG_TYPES_MAPPING:
            config_type = self.__class__.__name__.replace("Config", "").lower()
            logger.warning(f"You are attempting to create a config class from the base class `Config` which is "
                           f"not recommended!\n"
                           f"Your config class is {self.__class__.__name__} "
                           f"and the `config_type` will be `{config_type}`")
        else:
            config_type = CONFIG_TYPES_MAPPING[self.__class__.__name__].replace("Config", "").lower()
        return config_type

    def __getitem__(self, item):
        try:
            return self.dict()[item]
        except KeyError:
            raise AttributeError(f"`{self.__class__.__name__}` has no attribute `{item}`!")

    def __len__(self):
        return len(self.dict())

    def __iter__(self):
        return iter(self.dict())

    def dict(self):
        """
        Returns the config object as a dictionary (works on nested dataclasses too)

        Returns:
            The config object as a dictionary
        """
        return asdict(self)

    def keys(self):
        return list(self.dict().keys())

    def get(self, key, default=None):
        return getattr(self, key, default)

    def update(self, d: dict, **kwargs):
        """
        Update config with a given dictionary or keyword arguments. If a key does not exist in the attributes, prints a
        warning but sets it anyway.

        Args:
            d: A dictionary
            **kwargs: Key/value pairs in the form of keyword arguments

        Returns:
            The config object itself but the operation happens in-place anyway
        """
        d.update(kwargs)
        for k, v in d.items():
            if k not in self.__annotations__.keys():
                logger.warning(f"`{str(self.__class__.__name__)}` does not take `{k}` as a config parameter!")
            setattr(self, k, v)
        return self

    @classmethod
    def load(
        cls,
        hub_or_local_path: Union[str, os.PathLike],
        filename: Optional[str] = None,
        subfolder: Optional[str] = None,
        repo_type=None,
        **kwargs,
    ):
        """
        Load config from Hub or locally if it already exists on disk (handled by HfApi)

        Args:
            hub_or_local_path: Local or Hub path for the config
            filename: Configuration filename
            subfolder: Optional subfolder path where the config is in
            repo_type: Repo type e.g, model, dataset, etc
            **kwargs: Manual config parameters to override

        Returns:
            A Config instance
        """
        filename = filename or DEFAULT_MODEL_CONFIG_FILE
        subfolder = subfolder or ""

        config_path = os.path.join(hub_or_local_path, subfolder, filename)
        is_local = os.path.isfile(config_path)
        if os.path.isdir(hub_or_local_path) and not is_local:
            raise EnvironmentError(
                f"Path `{hub_or_local_path}` exists locally but the config file {filename} is missing!"
            )
        # if the file or repo_id does not exist locally, load from the Hub
        if not is_local:
            config_path = hf_hub_download(
                hub_or_local_path,
                filename=filename,
                subfolder=subfolder,
                cache_dir=HEZAR_CACHE_DIR,
                repo_type=repo_type,
            )

        dict_config = OmegaConf.load(config_path)
        config = OmegaConf.to_container(dict_config)
        config_cls = get_module_config_class(config["name"], config_type=config["config_type"])
        config = config_cls.from_dict(config, strict=False, **kwargs)
        return config

    @classmethod
    def from_dict(cls, dict_config: Union[Dict, DictConfig], **kwargs):
        """
        Load config from a dict-like object
        """
        # Update config parameters with kwargs
        dict_config.update(**kwargs)

        config = cls(**{k: v for k, v in dict_config.items() if hasattr(cls, k)})  # noqa

        return config

    def save(self, save_dir: Union[str, os.PathLike], filename: str, subfolder: Optional[str] = None):
        """
        Save the *config.yaml file to a local path

        Args:
             save_dir: Save directory path
             filename: Config file name
             subfolder: Subfolder to save the config file
        """
        subfolder = subfolder or ""
        config = self.dict()
        # exclude None items
        config = {k: v for k, v in config.items() if v is not None}
        # make and save to directory
        os.makedirs(os.path.join(save_dir, subfolder), exist_ok=True)
        save_path = os.path.join(save_dir, subfolder, filename)
        OmegaConf.save(config, save_path)
        return save_path

    def push_to_hub(
        self,
        repo_id: str,
        filename: str,
        subfolder: Optional[str] = None,
        repo_type: Optional[str] = "model",
        private: Optional[bool] = False,
        commit_message: Optional[str] = None,
    ):
        """
        Push the config file to the hub

        Args:
            repo_id (str): Repo name or id on the Hub
            filename (str): config file name
            subfolder (str): subfolder to save the config
            repo_type (str): Type of the repo e.g, model, dataset, space
            private (bool): Whether the repo type should be private or not (ignored if the repo exists)
            commit_message (str): Push commit message
        """
        path_in_repo = f"{subfolder}/{filename}" if subfolder else filename
        subfolder = subfolder or ""

        # create remote repo
        create_repo(repo_id, repo_type=repo_type, private=private, exist_ok=True)
        # save to tmp and prepare for push
        cache_path = tempfile.mkdtemp()
        config_path = self.save(cache_path, filename=filename, subfolder=subfolder)
        # push to hub
        if commit_message is None:
            commit_message = f"Hezar: Upload {filename}"
        upload_file(
            path_or_fileobj=config_path,
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=repo_type,
            commit_message=commit_message,
        )
        logger.info(
            f"Uploaded:`{self.__class__.__name__}(name={self.name})` --> `{os.path.join(repo_id, subfolder, filename)}`"
        )


@dataclass
class ModelConfig(Config):
    """
    Base dataclass for all model configs
    """


@dataclass
class PreprocessorConfig(Config):
    """
    Base dataclass for all preprocessor configs
    """


@dataclass
class DatasetConfig(Config):
    """
    Base dataclass for all dataset configs
    """
    task: Union[TaskType, List[TaskType]] = field(
        default=None, metadata={"help": "Name of the task(s) this dataset is built for"}
    )


@dataclass
class EmbeddingConfig(Config):
    """
    Base dataclass for all embedding configs
    """


@dataclass
class CriterionConfig(Config):
    """
    Base dataclass for all criterion configs
    """
    weight: Optional[torch.Tensor] = None
    reduce: str = None
    ignore_index: int = -100


@dataclass
class LRSchedulerConfig(Config):
    """
    Base dataclass for all scheduler configs
    """
    verbose: bool = True


@dataclass
class OptimizerConfig(Config):
    """
    Base dataclass for all optimizer configs
    """
    lr: float = None
    weight_decay: float = .0
    scheduler: Union[Dict[str, Any], LRSchedulerConfig] = None


@dataclass
class MetricConfig(Config):
    """
    Base dataclass config for all metric configs
    """


@dataclass
class TrainerConfig(Config):
    """
    Base dataclass for all trainer configs
    """
    task: TaskType = None
    device: str = "cuda"
    init_weights_from: str = None
    dataset_config: Union[DatasetConfig, Dict] = None
    num_dataloader_workers: int = 0
    seed: int = 42
    optimizer: Union[Dict[str, Any], OptimizerConfig] = None
    batch_size: int = None
    use_amp: bool = False
    metrics: Union[List[str], Dict[str, MetricConfig]] = None
    num_epochs: int = None
    save_freq: int = 1
    checkpoints_dir: str = None
    log_dir: str = None
