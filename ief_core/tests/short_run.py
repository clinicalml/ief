import torch
import torch.nn as nn
import numpy as np
import pytorch_lightning as pl
import sys 
import os
import optuna
from lifelines.utils import concordance_index
from sklearn.metrics import r2_score
from torch.utils.data import DataLoader, TensorDataset
from torchcontrib.optim import SWA
from pytorch_lightning import Trainer, seed_everything
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from argparse import ArgumentParser
from distutils.util import strtobool
sys.path.append('../')
sys.path.append('../../data/ml_mmrf')
sys.path.append('../../data/')
from ml_mmrf.ml_mmrf_v1.data import load_mmrf
from synthetic.synthetic_data import load_synthetic_data_trt, load_synthetic_data_noisy
from semi_synthetic.ss_data import *
from models.ssm.ssm import SSM, SSMAtt
from models.ssm.ssm_baseline import SSMBaseline
from models.rnn import GRU
from main_trainer import *
from models.fomm import FOMM, FOMMAtt
from models.sfomm import SFOMM
from distutils.util import strtobool

'''
Name: short_run.py 
Purpose: This set of functions is used to quickly train a model given a pre-determined
set of hyperparameters. In general, these are meant to be run after you have 
done a thorough hyperparameter sweep using launch_run.py. As in the other scripts, 
the args can be altered based on the user's needs (e.g. dataset, number of samples, 
using importance sampling or not for SSM, batch size, etc.).
Usage: If one wants to train an SSM model with a linear transition function on 20000 
samples of semi-synthetic, run -- train_ssm_gated_syn(ttype='lin', num_samples=20000).
'''

def train_ssm_gated_syn(ttype='attn_transition', num_samples=1000): 
    seed_everything(0)

    parser = ArgumentParser()
    parser.add_argument('--model_name', type=str, default='ssm', help='fomm, ssm, or gru')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate')
    parser.add_argument('--anneal', type=float, default=1., help='annealing rate')
    parser.add_argument('--fname', type=str, help='name of save file')
    parser.add_argument('--imp_sampling', type=bool, default=False, help='importance sampling to estimate marginal likelihood')
    parser.add_argument('--nsamples', default=1, type=int)
    parser.add_argument('--nsamples_syn', default=1000, type=int, help='number of training samples for synthetic data')
    parser.add_argument('--optimizer_name', type=str, default='adam')
    parser.add_argument('--dataset', default='semi_synthetic', type=str)
    parser.add_argument('--eval_type', type=str, default='nelbo')
    parser.add_argument('--loss_type', type=str, default='semisup')
    parser.add_argument('--bs', default=1500, type=int, help='batch size')
    parser.add_argument('--fold', default=1, type=int)
    parser.add_argument('--ss_missing', type=strtobool, default=False, help='whether to add missing data in semi synthetic setup or not')
    parser.add_argument('--ss_in_sample_dist', type=strtobool, default=True, help='whether to use mm training patients to generate validation/test set in semi synthetic data')
    parser.add_argument('--att_mask', type=strtobool, default=False, help='set to True for SSMAtt and FOMMAtt')
    import pdb; pdb.set_trace()
    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # add rest of args from SSM and base trainer
    parser = SSM.add_model_specific_args(parser)
    parser = Trainer.add_argparse_args(parser)

    # parse args and convert to dict
    args = parser.parse_args()
    args.max_epochs = 1000
    args.nsamples_syn = num_samples
    args.ttype      = ttype
    args.alpha1_type = 'linear'
    args.add_stochastic = False
    dict_args = vars(args)
    args.C = 0.01; args.reg_all = True; args.reg_type = 'l2'
    args.dim_stochastic = 128

    # initialize SSM w/ args and train 
    trial = optuna.trial.FixedTrial({'bs': args.bs, 'lr': args.lr, 'C': args.C, 'reg_all': args.reg_all, 'reg_type': args.reg_type, 'dim_stochastic': args.dim_stochastic})
    model = SSM(trial, **dict_args)
    checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/ssm_semi_syn_' + ttype + '_' + str(args.nsamples_syn) + 'sample_complexity{epoch:05d}-{val_loss:.2f}')
    trainer = Trainer.from_argparse_args(args, deterministic=True, logger=False, checkpoint_callback=False, gpus=[0])
    trainer.fit(model)

def train_ssm_gated_mm(fold=1, reg_all=True, C=0.01, reg_type='l2', ds=48, ttype='attn_transition', gpu=0, include_baseline='all', include_treatment='lines'):
    print(f'[FOLD: {fold}, REG_ALL: {reg_all}]') 
    seed_everything(0)

    parser = ArgumentParser()
    parser.add_argument('--model_name', type=str, default='ssm', help='fomm, ssm, or gru')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate')
    parser.add_argument('--anneal', type=float, default=1., help='annealing rate')
    parser.add_argument('--fname', type=str, help='name of save file')
    parser.add_argument('--imp_sampling', type=bool, default=False, help='importance sampling to estimate marginal likelihood')
    parser.add_argument('--nsamples', default=1, type=int)
    parser.add_argument('--nsamples_syn', default=100, type=int, help='number of training samples for synthetic data')
    parser.add_argument('--optimizer_name', type=str, default='adam')
    parser.add_argument('--dataset', default='mm', type=str)
    parser.add_argument('--eval_type', type=str, default='nelbo')
    parser.add_argument('--loss_type', type=str, default='unsup')
    parser.add_argument('--bs', default=600, type=int, help='batch size')
    parser.add_argument('--fold', default=fold, type=int)
    parser.add_argument('--ss_missing', type=strtobool, default=False, help='whether to add missing data in semi synthetic setup or not')
    parser.add_argument('--ss_in_sample_dist', type=strtobool, default=False, help='whether to use mm training patients to generate validation/test set in semi-synthetic data')
    parser.add_argument('--att_mask', type=strtobool, default=False, help='set to True for SSMAtt and FOMMAtt')

    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # add rest of args from SSM and base trainer
    parser = SSM.add_model_specific_args(parser)
    parser = Trainer.add_argparse_args(parser)

    # parse args and convert to dict
    args = parser.parse_args()
    args.max_epochs = 15000
    args.ttype      = ttype
    args.alpha1_type = 'linear'
    args.lr = 1e-3
    args.add_stochastic = False
    args.C = C; args.reg_all = reg_all; args.reg_type = reg_type
    args.include_baseline = include_baseline
    args.include_treatment = include_treatment
    args.dim_stochastic = ds
    dict_args = vars(args)

    # initialize FOMM w/ args and train 
    trial = optuna.trial.FixedTrial({'bs': args.bs, 'lr': args.lr, 'C': args.C, 'reg_all': args.reg_all, 'reg_type': args.reg_type, 'dim_stochastic': args.dim_stochastic})
    model = SSM(trial, **dict_args)
    checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/ablation/mmfold_reducedfeats' + str(fold) + str(ds) + '_' + ttype + '_' + include_baseline + include_treatment + '_ssm_baseablation{epoch:05d}-{val_loss:.2f}')
#     checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/new_ablation/mmfold_simulation_ia15' + str(fold) + str(ds) + '_' + ttype + '_' + '_ssm{epoch:05d}-{val_loss:.2f}')
    trainer = Trainer.from_argparse_args(args, deterministic=True, logger=False, checkpoint_callback=checkpoint_callback, gpus=[gpu])
    trainer.fit(model)
    
def train_sfomm_attn_mm(fold=1, reg_all=True, C=0.01, reg_type='l2', ds=16, mtype='linear'):
    print(f'[FOLD: {fold}, REG_ALL: {reg_all}]') 
    seed_everything(0)

    parser = ArgumentParser()
    parser.add_argument('--model_name', type=str, default='sfomm', help='fomm, ssm, or gru')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate')
    parser.add_argument('--anneal', type=float, default=1., help='annealing rate')
    parser.add_argument('--fname', type=str, help='name of save file')
    parser.add_argument('--imp_sampling', type=bool, default=False, help='importance sampling to estimate marginal likelihood')
    parser.add_argument('--nsamples', default=1, type=int)
    parser.add_argument('--nsamples_syn', default=100, type=int, help='number of training samples for synthetic data')
    parser.add_argument('--optimizer_name', type=str, default='adam')
    parser.add_argument('--dataset', default='mm', type=str)
    parser.add_argument('--eval_type', type=str, default='nelbo')
    parser.add_argument('--loss_type', type=str, default='unsup')
    parser.add_argument('--bs', default=600, type=int, help='batch size')
    parser.add_argument('--fold', default=fold, type=int)
    parser.add_argument('--ss_missing', type=strtobool, default=False, help='whether to add missing data in semi synthetic setup or not')
    parser.add_argument('--ss_in_sample_dist', type=strtobool, default=False, help='whether to use mm training patients to generate validation/test set in semi-synthetic data')
    parser.add_argument('--att_mask', type=strtobool, default=False, help='set to True for SSMAtt and FOMMAtt')

    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # add rest of args from SSM and base trainer
    parser = SFOMM.add_model_specific_args(parser)
    parser = Trainer.add_argparse_args(parser)

    # parse args and convert to dict
    args = parser.parse_args()
    args.max_epochs = 10000
    args.mtype      = mtype
    args.alpha1_type = 'linear'
    args.add_stochastic = False
    args.C = C; args.reg_all = reg_all; args.reg_type = reg_type
    args.dim_stochastic = ds
    args.inftype = 'rnn'
    dict_args = vars(args)

    # initialize SFOMM w/ args and train 
    trial = optuna.trial.FixedTrial({'bs': args.bs, 'lr': args.lr, 'C': args.C, 'reg_all': args.reg_all, 'reg_type': args.reg_type, 'dim_stochastic': args.dim_stochastic, 'inftype': args.inftype})
    model = SFOMM(trial, **dict_args)
    checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/mmfold' + str(fold) + str(ds) + '_sfomm_' + mtype + '_dataaug_fullfeat_test{epoch:05d}-{val_loss:.2f}')
    trainer = Trainer.from_argparse_args(args, deterministic=True, logger=False, checkpoint_callback=checkpoint_callback, gpus=[3])
    trainer.fit(model)
    
def train_fomm_gated(): 
    seed_everything(0)
    
    configs = [ 
        (1, 10000, 'attn_transition', .1, False, 'l1'),
        (1, 10000, 'linear', .1, True, 'l1')
    ]
    parser = ArgumentParser()
    parser.add_argument('--model_name', type=str, default='fomm_att', help='fomm, ssm, or gru')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate')
    parser.add_argument('--anneal', type=float, default=1., help='annealing rate')
    parser.add_argument('--fname', type=str, help='name of save file')
    parser.add_argument('--imp_sampling', type=bool, default=False, help='importance sampling to estimate marginal likelihood')
    parser.add_argument('--nsamples', default=1, type=int)
    parser.add_argument('--nsamples_syn', default=1000, type=int, help='number of training samples for synthetic data')
    parser.add_argument('--optimizer_name', type=str, default='adam')
    parser.add_argument('--eval_type', type=str, default='nelbo')
    parser.add_argument('--loss_type', type=str, default='unsup')
    parser.add_argument('--dataset', default='mm', type=str)
    parser.add_argument('--bs', default=600, type=int, help='batch size')
    parser.add_argument('--fold', default=1, type=int)
    parser.add_argument('--ss_missing', type=strtobool, default=False, help='whether to add missing data in semi synthetic setup or not')
    parser.add_argument('--ss_in_sample_dist', type=strtobool, default=False, help='whether to use mm training patients to generate validation/test set in semi synthetic data')
    parser.add_argument('--att_mask', type=strtobool, default=False, help='set to True for SSMAtt and FOMMAtt')


    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # add rest of args from FOMM and base trainer
    parser = FOMM.add_model_specific_args(parser)
    parser = Trainer.add_argparse_args(parser)
    
    for k,config in enumerate(configs): 
        print(f'running config: {config}')
        fold, max_epochs, mtype, C, reg_all, reg_type = config
        
        # parse args and convert to dict
        args = parser.parse_args()
        args.fold       = fold
        args.max_epochs = max_epochs
        args.dim_hidden = 300
        args.mtype      = mtype
        args.C = C; args.reg_all = reg_all; args.reg_type = reg_type
        args.alpha1_type = 'linear'
        args.otype = 'identity'
        print(f'FOLD: {args.fold}')
        args.add_stochastic = False
        dict_args = vars(args)

        # initialize FOMM w/ args and train
        trial = optuna.trial.FixedTrial({'bs': args.bs, 'lr': args.lr, 'C': args.C, 'reg_all': args.reg_all, 'reg_type': args.reg_type, 'dim_hidden': args.dim_hidden}) 
        model = FOMM(trial, **dict_args)
        checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/mmfold_' + str(fold) + mtype + '_dataaug_restrictedfeat_fomm_{epoch:05d}-{val_loss:.2f}')
        trainer = Trainer.from_argparse_args(args, deterministic=True, logger=False, gpus=[2], \
                        checkpoint_callback=checkpoint_callback, early_stop_callback=False)
        trainer.fit(model)

def train_gru(fold=1, reg_all=True, C=0.01, reg_type='l2', dh=250, mtype='gru', gpu=0, include_baseline='all', include_treatment='lines'): 
    print(f'[FOLD: {fold}, REG_ALL: {reg_all}]') 
    seed_everything(0)
    
#     configs = [
#         (1000, 'pkpd_gru_att', 500, 0.01, True, 'l2')
# #         (1000, 'gru', 250, 0.01, True, 'l2')
#     ]
    parser = ArgumentParser()
    parser.add_argument('--model_name', type=str, default='gru', help='fomm, ssm, or gru')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate')
    parser.add_argument('--anneal', type=float, default=1., help='annealing rate')
    parser.add_argument('--fname', type=str, help='name of save file')
    parser.add_argument('--imp_sampling', type=bool, default=False, help='importance sampling to estimate marginal likelihood')
    parser.add_argument('--nsamples', default=1, type=int)
    parser.add_argument('--nsamples_syn', default=100, type=int, help='number of training samples for synthetic data')
    parser.add_argument('--optimizer_name', type=str, default='adam')
    parser.add_argument('--dataset', default='mm', type=str)
    parser.add_argument('--eval_type', type=str, default='nelbo')
    parser.add_argument('--loss_type', type=str, default='unsup')
    parser.add_argument('--bs', default=600, type=int, help='batch size')
    parser.add_argument('--fold', default=fold, type=int)
    parser.add_argument('--optuna', type=strtobool, default=True, help='whether to use optuna to optimize hyperparams')
    parser.add_argument('--ss_missing', type=strtobool, default=False, help='whether to add missing data in semi synthetic setup or not')
    parser.add_argument('--ss_in_sample_dist', type=strtobool, default=False, help='whether to use mm training patients to generate validation/test set in semi synthetic data')
    parser.add_argument('--att_mask', type=strtobool, default=False, help='set to True for SSMAtt and FOMMAtt')


    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # add rest of args from GRU and base trainer
    parser = GRU.add_model_specific_args(parser)
    parser = Trainer.add_argparse_args(parser)
    
    # parse args and convert to dict
    args = parser.parse_args()
    args.max_epochs = 1000
    args.mtype      = mtype
    args.dim_hidden = dh
    args.reg_type   = reg_type
    args.C          = C
    args.reg_all    = reg_all
    args.alpha1_type = 'linear'
    args.add_stochastic = False
    args.include_baseline = include_baseline 
    args.include_treatment= include_treatment
    dict_args = vars(args)

    # initialize FOMM w/ args and train 
    trial = optuna.trial.FixedTrial({'bs': args.bs,'lr': args.lr, 'C': args.C, 'reg_all': args.reg_all, 'reg_type': args.reg_type, 'dim_hidden': args.dim_hidden}) 
    model = GRU(trial, **dict_args)
        # early_stop_callback = EarlyStopping(
        #    monitor='val_loss',
        #    min_delta=0.00,
        #    patience=10,
        #    verbose=False,
        #    mode='min'
        # )
    checkpoint_callback = ModelCheckpoint(filepath='./checkpoints/new_ablation/gru_simulation_ia15{epoch:05d}-{val_loss:.2f}')
    trainer = Trainer.from_argparse_args(args, deterministic=True, logger=False, gpus=[gpu], \
            early_stop_callback=False, checkpoint_callback=checkpoint_callback)
    trainer.fit(model)


if __name__ == '__main__':
    parser = ArgumentParser()
    # figure out which model to use and other basic params
    parser.add_argument('--model_name', type=str, default='pkpd')
    parser.add_argument('--gpu', type=int, default=0)
    parser.add_argument('--include_baseline', type=str, default='all')
    parser.add_argument('--include_treatment', type=str, default='all')
    parser = Trainer.add_argparse_args(parser)
    args = parser.parse_args()
    
    if args.model_name == 'gru': 
        hs = [250,500,100,750]
        for h in hs:
            train_gru(fold=1, reg_all=True, C=0.01, reg_type='l2', dh=h, mtype='gru', gpu=args.gpu)
    else: 
        sizes = [48,64]
        # no aug, full feature set 
        for ds in sizes: 
            if args.model_name == 'pkpd':
                train_ssm_gated_mm(fold=1, reg_all=True, C=0.01, reg_type='l1', ds=ds, ttype='attn_transition', \
                                   gpu=args.gpu, include_baseline=args.include_baseline, include_treatment=args.include_treatment)
            elif args.model_name == 'lin': 
                train_ssm_gated_mm(fold=1, reg_all=True, C=0.01, reg_type='l2', ds=16, ttype='lin', gpu=args.gpu)
            elif args.model_name == 'nl': 
                train_ssm_gated_mm(fold=1, reg_all=True, C=0.1, reg_type='l2', ds=48, ttype='nl', gpu=args.gpu)
            elif args.model_name == 'moe': 
                train_ssm_gated_mm(fold=1, reg_all=True, C=0.1, reg_type='l2', ds=48, ttype='moe', gpu=args.gpu)
            
    

