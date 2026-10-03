import pandas as pd
import numpy as np

df = pd.read_csv('/c/Users/user/.hermes/desktop-attachments/Supplementary_Data_4_BAM_DEanalysis_2026-01-21 16-44-37.csv')
print('Shape:', df.shape)
print('Columns:', list(df.columns))
print()
print('Cluster counts:')
print(df['cluster'].value_counts().sort_index())
print()
print('PF4+ clusters:', sorted([2,3,4,8,13,14,19]))
print('VSIG4+ clusters:', sorted([20,18,10]))

sig = df[(df['p_val'] < 0.01) & (df['avg_log2FC'].abs() > 0.25)].copy()
print()
print(f'Total sig rows: {len(sig)}')

pf4_clusters = [2,3,4,8,13,14,19]
vsig_clusters = [20,18,10]

pf4_sig = sig[sig['cluster'].isin(pf4_clusters)]
vsig_sig = sig[sig['cluster'].isin(vsig_clusters)]
print(f'PF4+ sig: {len(pf4_sig)}, VSIG4+ sig: {len(vsig_sig)}')
