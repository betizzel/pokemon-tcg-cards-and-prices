# Class-level clustering results

K-means groups 29,877 products using age, rarity, and printing.
Age is standardized. Categories use plain 0/1 columns; no custom category weights are applied.
K=4 is a working choice for continuity with the original project, not a proven optimum.
The elbow plot reports SSE for K=1 through K=8 on the same full dataset.

## Cluster descriptions and final-month prices

```text
 cluster  products  mean_age_years most_common_rarity most_common_printing   month  median_price_usd  products_with_price
       0      7236           19.84             Common                 base 2024-11              2.87                 7195
       1      6865            5.17             Common         reverse-holo 2024-11              1.52                 6817
       2      5021           16.80             Common         reverse-holo 2024-11              4.00                 5010
       3     10755            5.94             Common                 base 2024-11              1.50                10737
```

## Reading the history

Monthly summaries cover 2020-12 through 2024-11.
Prices are compared after fitting and never determine the clusters.
Use the price chart and observation-count chart together. December 2020 is sparse, and October 2024 has fewer observations.
A change in the group median can reflect different products being observed. It is not the return on a fixed collection of cards.
The groups stay fixed using age at November 2024; this is descriptive unsupervised learning, not future-price prediction.
Cluster numbers are arbitrary. Removing the previous custom category weighting changes assignments, so older cluster labels and results cannot be reused.

## Connection to class

CSE4334_Clustering.pptx: unsupervised learning (slides 3–6), similarity (11), Euclidean distance and K-means (43–51), limitations (57), SSE/elbow method (58–59), and normalization (65–66).
Converting categories to numeric indicators is project preprocessing. The lecture warns about using means on raw categories; indicator centroids are proportions, not literal card categories.
