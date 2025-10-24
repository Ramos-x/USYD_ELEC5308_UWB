#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于采集到的 CSV 训练一个简单的回归模型，输出 model.pkl。
注意：需要手动提供“真值距离”列 dist_m（或 dist_cm / dist_mm 之一）。
你可以在 collect_uwb.py 输出 CSV 后，用 Excel/脚本添加真值，并命名为 dist_m（单位：米）。

用法：
  python train_distance_model.py --in data_labeled.csv --out model.pkl

该脚本采用 scikit-learn 的 GradientBoostingRegressor 作为 baseline。
若未安装，请 pip install scikit-learn pandas numpy joblib
"""
import argparse
import pandas as pd
import numpy as np
from joblib import dump

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error


FEATURES = [
    'dt_tx1_rx2','dt_rx2_tx3p','dt_rx2_tx3r',
    'qual_cia','qual_xo','ipatov_peak','ipatov_pwr','ipatov_fp_idx','ipatov_acc'
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='infile', required=True, help='输入 CSV（包含 dist_m）')
    p.add_argument('--out', default='model.pkl', help='输出模型文件')
    return p.parse_args()


def main():
    args = parse_args()
    df = pd.read_csv(args.infile)

    # 兼容不同真值字段名
    if 'dist_m' in df.columns:
        y = df['dist_m'].values
    elif 'dist_cm' in df.columns:
        y = df['dist_cm'].values / 100.0
    elif 'dist_mm' in df.columns:
        y = df['dist_mm'].values / 1000.0
    else:
        raise SystemExit('CSV 中需要包含 dist_m / dist_cm / dist_mm 之一作为监督信号')

    X = df.reindex(columns=FEATURES).fillna(0.0).values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = GradientBoostingRegressor(random_state=42)
    model.fit(X_train, y_train)

    pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, pred)
    print(f'MAE = {mae:.3f} m on {len(y_test)} samples')

    dump({'model': model, 'features': FEATURES}, args.out)
    print('Saved to', args.out)


if __name__ == '__main__':
    main()
