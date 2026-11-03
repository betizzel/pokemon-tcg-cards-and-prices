"""Class-level K-means analysis and monthly ungraded prices.

Run: python longitudinal.py
See Clustering_Longitudinal.ipynb for the same steps with explanations.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from main import DATA_DIR, load_cards, load_data

OUTPUT = Path(__file__).parent / "results" / "longitudinal"
CHOSEN_K = 4


def load_products():
    """One row per printing; prices are not used to choose these rows."""
    links = pd.read_csv(DATA_DIR / "card_links.csv", dtype={"pc_id": str}, keep_default_na=False)
    cards = load_cards()[["card_id", "name", "rarity", "set_release_date"]]
    products = links.merge(cards, on="card_id", how="left", validate="many_to_one")
    if products.pc_id.duplicated().any():
        raise ValueError("Each product must appear only once")
    products["variant"] = products.variant.replace("", "base")
    products["rarity"] = products.rarity.replace(r"^\s*$", np.nan, regex=True)
    products = products.dropna(subset=["rarity", "set_release_date"])
    products = products.loc[products.set_release_date <= "2024-11-30"].copy()
    products["age_years"] = (pd.Timestamp("2024-11-30") - products.set_release_date).dt.days / 365.25
    return products.reset_index(drop=True)


def make_features(products):
    """Standardize age; represent rarity and printing with plain 0/1 columns."""
    features = pd.get_dummies(products[["rarity", "variant"]], dtype=float)
    features["age_years"] = StandardScaler().fit_transform(products[["age_years"]]).ravel()
    return features


def compare_k(features, chosen_k=CHOSEN_K):
    """SSE is the sum of squared Euclidean distances to assigned centroids."""
    rows = []
    chosen_model = None
    with threadpool_limits(limits=1):
        for k in range(1, 9):
            model = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300, tol=0)
            model.fit(features)
            rows.append({"k": k, "sse": model.inertia_})
            if k == chosen_k:
                chosen_model = model
    if chosen_model is None:
        raise ValueError("Choose K between 1 and 8")
    return pd.DataFrame(rows), chosen_model


def monthly_prices(panel, products):
    """Simple monthly medians and counts, with missing months left missing."""
    history = panel[["pc_id", "month", "price_ungraded"]].merge(
        products[["pc_id", "cluster", "set_release_date"]], on="pc_id", validate="many_to_one")
    if history.duplicated(["pc_id", "month"]).any():
        raise ValueError("Duplicate product/month rows")
    # Keep the release month; exact dates cannot be compared to monthly prices.
    before_release = history.month < history.set_release_date.dt.strftime("%Y-%m")
    print(f"Removed {int(before_release.sum()):,} rows before the listed set release month.")
    history = history.loc[~before_release].copy()
    history["price_ungraded"] = history.price_ungraded.where(
        np.isfinite(history.price_ungraded) & (history.price_ungraded > 0))
    monthly = history.groupby(["cluster", "month"]).agg(
        median_price_usd=("price_ungraded", "median"),
        products_with_price=("price_ungraded", "count"),
    )
    calendar = pd.period_range(panel.month.min(), panel.month.max(), freq="M").astype(str)
    index = pd.MultiIndex.from_product([sorted(products.cluster.unique()), calendar], names=["cluster", "month"])
    monthly = monthly.reindex(index).reset_index()
    monthly["products_with_price"] = monthly.products_with_price.fillna(0).astype(int)
    return monthly


def describe_clusters(products):
    return products.groupby("cluster").agg(
        products=("pc_id", "size"),
        mean_age_years=("age_years", "mean"),
        most_common_rarity=("rarity", lambda x: x.mode().iloc[0]),
        most_common_printing=("variant", lambda x: x.mode().iloc[0]),
    ).reset_index()


def save_results(products, features, model, elbow, monthly):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    profiles = describe_clusters(products)
    elbow.to_csv(OUTPUT / "elbow.csv", index=False)
    profiles.to_csv(OUTPUT / "cluster_summary.csv", index=False)
    monthly.to_csv(OUTPUT / "monthly_prices.csv", index=False)
    pd.DataFrame(model.cluster_centers_, columns=features.columns).rename_axis("cluster").to_csv(OUTPUT / "centroids.csv")
    products.to_parquet(OUTPUT / "product_clusters.parquet", index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(elbow.k, elbow.sse, marker="o")
    ax.axvline(model.n_clusters, linestyle="--", color="grey", label=f"Working choice: K={model.n_clusters}")
    ax.set(xlabel="Number of clusters (K)", ylabel="Sum of squared errors (SSE)", title="Elbow method: K-means on card characteristics", xticks=elbow.k)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT / "elbow.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for cluster, group in monthly.groupby("cluster"):
        dates = pd.to_datetime(group.month)
        axes[0].plot(dates, group.median_price_usd, label=f"Cluster {cluster}")
        axes[1].plot(dates, group.products_with_price)
    axes[0].set(title="Monthly ungraded prices for fixed characteristic clusters", ylabel="Median price (USD)")
    axes[0].legend()
    axes[1].set(title="Number of products supporting each monthly median", ylabel="Products with a price", xlabel="Month")
    for ax in axes:
        ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(OUTPUT / "monthly_prices.png", dpi=150)
    plt.close(fig)

    last = monthly.loc[monthly.month == monthly.month.max()]
    summary = profiles.merge(last, on="cluster")
    text = ["# Class-level clustering results", "",
            f"K-means groups {len(products):,} products using age, rarity, and printing.",
            "Age is standardized. Categories use plain 0/1 columns; no custom category weights are applied.",
            "K=4 is a working choice for continuity with the original project, not a proven optimum.",
            "The elbow plot reports SSE for K=1 through K=8 on the same full dataset.", "",
            "## Cluster descriptions and final-month prices", "", "```text",
            summary.round(2).to_string(index=False), "```", "",
            "## Reading the history", "",
            f"Monthly summaries cover {monthly.month.min()} through {monthly.month.max()}.",
            "Prices are compared after fitting and never determine the clusters.",
            "Use the price chart and observation-count chart together. December 2020 is sparse, and October 2024 has fewer observations.",
            "A change in the group median can reflect different products being observed. It is not the return on a fixed collection of cards.",
            "The groups stay fixed using age at November 2024; this is descriptive unsupervised learning, not future-price prediction.",
            "Cluster numbers are arbitrary. Removing the previous custom category weighting changes assignments, so older cluster labels and results cannot be reused.", "",]
    (OUTPUT / "SUMMARY.md").write_text("\n".join(text), encoding="utf-8")
    return summary


def run():
    products = load_products()
    features = make_features(products)
    elbow, model = compare_k(features)
    products["cluster"] = model.labels_
    monthly = monthly_prices(load_data(), products)
    summary = save_results(products, features, model, elbow, monthly)
    print(summary.round(2).to_string(index=False))
    return summary


if __name__ == "__main__":
    run()
