"""Utilities for PyTorch Lightning DataModule.

Todo:
    * Add usage (Example Section).
    * Add unit-test.
"""
import copy
from logging import getLogger
from typing import Dict, List, Optional, Tuple

import pytorch_lightning as pl
import torch
from omegaconf import DictConfig
from torch.utils.data import DataLoader

from openpack_torch.data.utils import assemble_sequence_list_from_cfg

log = getLogger(__name__)


class OpenPackBaseDataModule(pl.LightningDataModule):
    """Base class of PyTorch Lightning DataModule.
    A datamodule is a shareable, reusable class that encapsulates all the steps needed to process
    data:

    Attributes:
        dataset_class (torch.utils.data.Dataset): dataset class. this variable is call to create
            dataset instances.
        cfg (DictConfig): config object. The all parameters used to initialuze dataset class should
            be included in this object.
        batch_size (int): batch size.
        debug (bool): If True, enable debug mode.
    """

    dataset_class: torch.utils.data.Dataset

    def __init__(self, cfg: DictConfig):
        super().__init__()
        self.cfg = cfg

        self.debug = cfg.debug
        if cfg.debug:
            self.batch_size = cfg.train.debug.batch_size
        else:
            self.batch_size = cfg.train.batch_size

    def get_kwargs_for_datasets(self, stage: Optional[str] = None) -> Dict:
        """Build a kwargs to initialize dataset class. This method is called in ``setup()``.

        Args:
            stage (str, optional): dataset type. {train, validate, test, submission}.

        Example:

            ::

                def get_kwargs_for_datasets(self) -> Dict:
                    kwargs = {
                        "window": self.cfg.train.window,
                        "debug": self.cfg.debug,
                    }
                    return kwargs

        Returns:
            Dict:
        """
        kwargs = {
            "window": self.cfg.train.window,
            "debug": self.cfg.debug,
        }
        return kwargs

    def _init_datasets(
        self,
        user_session: Tuple[int, int],
        kwargs: Dict,
    ) -> Dict[str, torch.utils.data.Dataset]:
        """Returns list of initialized dataset object.

        Args:
            rootdir (Path): _description_
            user_session (Tuple[int, int]): _description_
            kwargs (Dict): _description_

        Returns:
            Dict[str, torch.utils.data.Dataset]: dataset objects
        """
        datasets = dict()
        for user, session in user_session:
            key = f"{user}-{session}"
            datasets[key] = self.dataset_class(
                copy.deepcopy(self.cfg), [(user, session)], **kwargs
            )
        return datasets

    def setup(self, stage: Optional[str] = None) -> None:
        if hasattr(self.cfg.dataset.split, "spec"):
            split = self.cfg.dataset.split.spec
        else:
            split = self.cfg.dataset.split

        if stage in (None, "fit"):
            kwargs = self.get_kwargs_for_datasets(stage="train")
            self.op_train = self.dataset_class(self.cfg, split.train, **kwargs)
            if self.cfg.train.random_crop:
                self.op_train.random_crop = True
                log.debug(f"enable random_crop in training dataset: {self.op_train}")
        else:
            self.op_train = None

        if stage in (None, "fit", "validate"):
            kwargs = self.get_kwargs_for_datasets(stage="validate")
            self.op_val = self._init_datasets(split.val, kwargs)
        else:
            self.op_val = None

        if stage in (None, "test"):
            kwargs = self.get_kwargs_for_datasets(stage="test")
            self.op_test = self._init_datasets(split.test, kwargs)
        else:
            self.op_test = None

        if stage in (None, "submission"):
            kwargs = self.get_kwargs_for_datasets(stage="submission")
            kwargs.update({"submission": True})
            self.op_submission = self._init_datasets(split.submission, kwargs)
        elif stage == "test-on-submission":
            kwargs = self.get_kwargs_for_datasets(stage="submission")
            self.op_submission = self._init_datasets(split.submission, kwargs)
        else:
            self.op_submission = None

        log.info(f"dataset[train]: {self.op_train}")
        log.info(f"dataset[val]: {self.op_val}")
        log.info(f"dataset[test]: {self.op_test}")
        log.info(f"dataset[submission]: {self.op_submission}")

    def train_dataloader(self) -> DataLoader:
        return DataLoader(
            self.op_train,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.cfg.train.num_workers,
        )

    def val_dataloader(self) -> List[DataLoader]:
        dataloaders = []
        for key, dataset in self.op_val.items():
            dataloaders.append(
                DataLoader(
                    dataset,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=self.cfg.train.num_workers,
                )
            )
        return dataloaders

    def test_dataloader(self) -> List[DataLoader]:
        dataloaders = []
        for key, dataset in self.op_test.items():
            dataloaders.append(
                DataLoader(
                    dataset,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=self.cfg.train.num_workers,
                )
            )
        return dataloaders

    def submission_dataloader(self) -> List[DataLoader]:
        dataloaders = []
        for key, dataset in self.op_submission.items():
            dataloaders.append(
                DataLoader(
                    dataset,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=self.cfg.train.num_workers,
                )
            )
        return dataloaders


class OpenPackBaseFlexSetDataModule(OpenPackBaseDataModule):
    dataset_train = None
    dataset_val = None
    dataset_test = None

    def _init_datasets(
        self,
        user_session: Tuple[int, int],
        kwargs: Dict,
    ) -> Dict[str, torch.utils.data.Dataset]:
        """Returns list of initialized dataset object.
        Args:
            rootdir (Path): _description_
            user_session (Tuple[int, int]): _description_
            kwargs (Dict): _description_
        Returns:
            Dict[str, torch.utils.data.Dataset]: dataset objects
        """
        datasets = dict()
        for user, session in user_session:
            key = f"{user}-{session}"
            datasets[key] = self.dataset_class(
                copy.deepcopy(self.cfg), [(user, session)], **kwargs
            )
        return datasets

    def setup(self, stage: Optional[str] = None) -> None:
        split = self.cfg.dataset.split

        if stage in (None, "fit"):
            kwargs = self.get_kwargs_for_datasets(stage="fit")
            split = assemble_sequence_list_from_cfg(self.cfg, stage)
            self.dataset_train = self.dataset_class(self.cfg, split, **kwargs)
        else:
            self.dataset_train = None

        # TODO: Generate ValDataset from Train.
        if stage in (None, "fit", "validate"):
            self.dataset_train, self.dataset_val = split_dataset(
                self.cfg,
                self.dataset_train,
                val_split_size=self.cfg.train.val_split_siz,
            )
        else:
            self.dataset_val = None

        if stage in (None, "test"):
            kwargs = self.get_kwargs_for_datasets(stage="test")
            split = assemble_sequence_list_from_cfg(self.cfg, stage)
            self.dataset_test = self._init_datasets(split, kwargs)
        else:
            self.dataset_test = None

        log.info(f"dataset[train]: {self.dataset_train}")
        log.info(f"dataset[val]: {self.dataset_val}")
        log.info(f"dataset[test]: {self.dataset_test}")

    def train_dataloader(self) -> DataLoader:
        return DataLoader(
            self.dataset_train,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.cfg.train.num_workers,
        )

    def val_dataloader(self) -> List[DataLoader]:
        return DataLoader(
            self.dataset_val,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.cfg.train.num_workers,
        )

    def test_dataloader(self) -> List[DataLoader]:
        dataloaders = []
        for key, dataset in self.dataset_test.items():
            dataloaders.append(
                DataLoader(
                    dataset,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=self.cfg.train.num_workers,
                )
            )
        return dataloaders

    def submission_dataloader(self) -> List[DataLoader]:
        dataloaders = []
        for key, dataset in self.dataset_submission.items():
            dataloaders.append(
                DataLoader(
                    dataset,
                    batch_size=self.batch_size,
                    shuffle=False,
                    num_workers=self.cfg.train.num_workers,
                )
            )
        return dataloaders
