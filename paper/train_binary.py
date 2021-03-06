import warnings
warnings.filterwarnings('ignore')
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=FutureWarning)
import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

import torch
from models.models import LeNetMadry
from models import resnet_orig as resnet
from models import hendrycks as resnet_oe
from laplace import llla, kfla, dla
import laplace.util as lutil
from pycalib.calibration_methods import TemperatureScaling
from util.evaluation import *
from util.tables import *
import util.dataloaders as dl
from util.misc import *
from tqdm import tqdm, trange
import numpy as np
import argparse
import pickle
import os


parser = argparse.ArgumentParser()
parser.add_argument('--dataset', help='Pick one \\{"MNIST", "CIFAR10", "SVHN", "CIFAR100"\\}', default='MNIST')
parser.add_argument('--randseed', type=int, default=123)
args = parser.parse_args()

np.random.seed(args.randseed)
torch.manual_seed(args.randseed)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

if args.dataset == 'MNIST':
    class1, class2 = 3, 8
    train_loader = dl.binary_MNIST(class1, class2, train=True)
    val_loader, test_loader = dl.binary_MNIST(class1, class2, train=False, augm_flag=False, val_size=1000)
elif args.dataset == 'CIFAR10':
    class1, class2 = 5, 3
    train_loader = dl.binary_CIFAR10(class1, class2, train=True)
    val_loader, test_loader = dl.binary_CIFAR10(class1, class2, train=False, augm_flag=False,  val_size=1000)
elif args.dataset == 'SVHN':
    class1, class2 = 3, 9
    train_loader = dl.binary_SVHN(class1, class2, train=True)
    val_loader, test_loader = dl.binary_SVHN(class1, class2, train=False, augm_flag=False,  val_size=1000)
elif args.dataset == 'CIFAR100':
    print('a')
    class1, class2 = 47, 52
    train_loader = dl.binary_CIFAR100(class1, class2, train=True)
    val_loader, test_loader = dl.binary_CIFAR100(class1, class2, train=False, augm_flag=False,  val_size=100)
    print(len(train_loader.dataset), len(val_loader.dataset), len(test_loader.dataset))

targets = torch.cat([y for x, y in test_loader], dim=0).numpy()
targets_val = torch.cat([y for x, y in val_loader], dim=0).numpy()

print(len(train_loader.dataset), len(val_loader.dataset), len(test_loader.dataset))

model = LeNetMadry(binary=True) if args.dataset == 'MNIST' else resnet.ResNet18(num_classes=2)
model.cuda()
model.train()

if args.dataset == 'MNIST':
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=5e-4)
else:
    opt = torch.optim.SGD(model.parameters(), lr=0.1, momentum=0.9, weight_decay=5e-4)

criterion = torch.nn.BCEWithLogitsLoss()
pbar = trange(100)

for epoch in pbar:
    if epoch+1 in [50,75,90]:
        for group in opt.param_groups:
            group['lr'] *= .1

    train_loss = 0
    n = 0

    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.cuda(), target.float().cuda()

        output = model(data).squeeze()
        loss = criterion(output, target)

        opt.zero_grad()
        loss.backward()
        opt.step()

        train_loss += loss.item()
        n += 1

    train_loss /= n
    pred_val = predict_binary(val_loader, model).cpu().numpy()
    acc_val = np.mean((pred_val >= 0.5) == targets_val)*100

    pbar.set_description(f'[Epoch: {epoch+1}; train_loss: {train_loss:.4f}; val_acc: {acc_val:.1f}]')

torch.save(model.state_dict(), f'./pretrained_models/binary_{args.dataset}.pt')

model.load_state_dict(torch.load(f'./pretrained_models/binary_{args.dataset}.pt'))
model.eval()

print()

# In-distribution
py_in, time_pred = timing(lambda: predict_binary(test_loader, model).cpu().numpy())
acc_in = np.mean((py_in >= 0.5) == targets)
mmc = np.maximum(py_in, 1-py_in).mean()
# ece, mce = get_calib(py_in, targets)
ece, mce = 0, 0
print(f'[In, MAP] Time: NA/{time_pred:.1f}s; Accuracy: {acc_in:.3f}; ECE: {ece:.3f}; MCE: {mce:.3f}; MMC: {mmc:.3f}')
