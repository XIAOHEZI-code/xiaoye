import matplotlib.pyplot as plt
import numpy as np

# Data
queries = ['Q1: Converter\nCarbon', 'Q2: Rare Earth\nBearing Steel', 'Q3: Casting\nBreakout']
no_hyde_keywords = [8, 8, 7]
hyde_keywords = [31, 40, 39]

x = np.arange(len(queries))
width = 0.35

fig, ax = plt.subplots(figsize=(8, 5))
rects1 = ax.bar(x - width/2, no_hyde_keywords, width, label='Traditional Search', color='#3498db')
rects2 = ax.bar(x + width/2, hyde_keywords, width, label='HyDE Enhanced', color='#e74c3c')

ax.set_ylabel('Expanded Semantic Features Count', fontsize=12)
ax.set_title('HyDE Semantic Expansion Comparison Across 3 Test Queries', fontsize=14)
ax.set_xticks(x)
ax.set_xticklabels(queries, fontsize=11)
ax.legend(fontsize=12)

ax.bar_label(rects1, padding=3)
ax.bar_label(rects2, padding=3)

fig.tight_layout()
plt.savefig('hyde_comparison.png', dpi=300)
print("Chart generated: hyde_comparison.png")
