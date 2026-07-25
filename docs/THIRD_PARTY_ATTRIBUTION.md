# Third-Party Attribution and Data Sources

## Reference Fraud Repository

- **Project:** Credit-Card-Fraud-Detection
- **Author credited by upstream README:** Taher Alabbar
- **Upstream:** <https://github.com/TaherAlabbr/Credit-Card-Fraud-Detection>
- **Local reference snapshot:** `Fraud Detection/`
- **Use in this project:** audit and learning reference only

No license file was found in the supplied local or upstream repository during the Phase 0 audit. Therefore:

- application code must not import from the snapshot
- source code must not be copied into first-party modules
- bundled serialized models must not be redistributed
- permission or a clear license is required before reuse beyond local evaluation

The project will independently implement and train its own Phase 1 ML baseline.

## ULB/Kaggle Credit Card Fraud Dataset

- **Local file:** `dataset/creditcard.csv`
- **Common source page:** <https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud>
- **Original context:** European cardholder transactions represented by `Time`, `Amount`, anonymized PCA features `V1`–`V28`, and binary `Class`
- **Use in this project:** supervised card-fraud benchmark only; not AML typology ground truth

The dataset must remain outside Git. Before distribution or publication, verify and comply with the current dataset terms on the source page and include any citation requested by its maintainers.

## Python Dependencies

Runtime and development dependencies are declared in `pyproject.toml`. Their own licenses apply. A distributable release should generate a dependency license report as part of release review.
