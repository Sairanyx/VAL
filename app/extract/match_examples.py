"""Label objects by comparing them to labelled examples from the same room. Runs offline.

    python -m app.extract.match_examples features ASSETS.json MASKS_DIR OUT.npz --model NAME
    python -m app.extract.match_examples evaluate FEATURES.npz LABELS.json

`features` makes one image feature per object, averaged over its views. `evaluate` holds out each
fold of labelled objects in turn, so scores reflect objects the method hasn't seen.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

IGNORED_FOR_TRAINING = {"unknown"}


def normalize(features: np.ndarray) -> np.ndarray:
    return features / np.clip(np.linalg.norm(features, axis=1, keepdims=True), 1e-9, None)


def knn_predict(
    train_features: np.ndarray,
    train_labels: list[str],
    test_features: np.ndarray,
    k: int = 5,
) -> tuple[list[str], np.ndarray]:
    """Return the similarity-weighted majority label of the k nearest examples, and its share."""
    similarity = normalize(test_features) @ normalize(train_features).T
    k = min(k, len(train_labels))
    labels, shares = [], []
    for row in similarity:
        nearest = np.argsort(-row)[:k]
        votes: dict[str, float] = {}
        for index in nearest:
            votes[train_labels[index]] = votes.get(train_labels[index], 0.0) + max(row[index], 0.0)
        best = max(votes, key=votes.get)
        labels.append(best)
        shares.append(votes[best] / max(sum(votes.values()), 1e-9))
    return labels, np.array(shares)


def cross_validate(
    features: np.ndarray, labels: list[str], folds: int = 5, k: int = 5, seed: int = 0
) -> tuple[list[str], np.ndarray]:
    """Return held-out predictions and shares for every object."""
    order = np.random.default_rng(seed).permutation(len(labels))
    predictions: list[str] = [""] * len(labels)
    shares = np.zeros(len(labels))
    for fold in range(folds):
        test = order[fold::folds]
        train = np.setdiff1d(order, test)
        train = np.array([index for index in train if labels[index] not in IGNORED_FOR_TRAINING])
        guessed, confidence = knn_predict(
            features[train], [labels[index] for index in train], features[test], k=k
        )
        for index, label, share in zip(test, guessed, confidence, strict=True):
            predictions[index], shares[index] = label, share
    return predictions, shares


def compute_features(
    assets: list[dict], masks_dir: Path, model_name: str, views: int
) -> np.ndarray:
    """Return one averaged image feature per object, from focused crops. Needs a GPU."""
    import torch

    from app.extract.label_objects import object_crops

    source, _, name = model_name.partition(":")
    if source == "clip":
        import open_clip

        arch, _, pretrained = name.partition("/")
        model, _, preprocess = open_clip.create_model_and_transforms(arch, pretrained=pretrained)
        encode = model.encode_image
    else:
        import timm

        model = timm.create_model(name, pretrained=True, num_classes=0)
        config = timm.data.resolve_model_data_config(model)
        preprocess = timm.data.create_transform(**config, is_training=False)
        encode = model
    model = model.to("cuda").eval()

    rows = []
    with torch.inference_mode():
        for asset in assets:
            crops = object_crops(asset, masks_dir, views)
            batch = torch.stack([preprocess(crop.convert("RGB")) for crop in crops]).to("cuda")
            found = encode(batch).float()
            found = found / found.norm(dim=-1, keepdim=True)
            rows.append(found.mean(dim=0).cpu().numpy())
    return np.stack(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("features")
    make.add_argument("assets", type=Path)
    make.add_argument("masks_dir", type=Path)
    make.add_argument("out", type=Path)
    make.add_argument("--model", default="clip:ViT-B-16/laion2b_s34b_b88k")
    make.add_argument("--views", type=int, default=5)
    check = commands.add_parser("evaluate")
    check.add_argument("features", type=Path)
    check.add_argument("labels", type=Path)
    check.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    if args.command == "features":
        assets = json.loads(args.assets.read_text())["assets"]
        features = compute_features(assets, args.masks_dir, args.model, args.views)
        ids = np.array([asset["object_id"] for asset in assets])
        np.savez_compressed(args.out, features=features, ids=ids)
        print(f"{features.shape} features from {args.model}")
        return

    loaded = np.load(args.features)
    review = json.loads(args.labels.read_text())
    ids = loaded["ids"].tolist()
    labels = [review[item] for item in ids]
    predictions, _ = cross_validate(loaded["features"], labels, k=args.k)
    scored = [i for i, label in enumerate(labels) if label != "unknown"]
    correct = sum(predictions[i] == labels[i] for i in scored)
    print(f"held-out agreement on {len(scored)} named objects: {correct / len(scored):.0%}")
    for name, count in Counter(labels[i] for i in scored).most_common():
        members = [i for i in scored if labels[i] == name]
        claimed = [i for i in scored if predictions[i] == name]
        found = sum(predictions[i] == name for i in members)
        right = sum(labels[i] == name for i in claimed)
        print(
            f"  {name:20s} examples {count:3d}  found {found:3d}  "
            f"claimed {len(claimed):3d}  right {right:3d}"
        )


if __name__ == "__main__":
    main()
