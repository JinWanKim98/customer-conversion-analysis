# Source attribution and release scope

Review date: 2026-10-28. This records the observed source statements and the project's file-handling decision; it does not grant new dataset rights.

| Source | Evidence captured | Project handling |
|---|---|---|
| REES46 electronics events | Provider links the exact Kaggle dataset. Kaggle official API metadata lists **Data files © Original Authors**, updated 2021-03-29. | Attribute REES46/Michael Kechinov; preserve original hashes. Do not include source rows, raw archives or ID-bearing SQLite models in a shareable package. |
| Hillstrom 2008 | Author publishes a randomized-email analysis challenge and invites reporting findings. TensorFlow describes schema/design; the scikit-uplift loader documents the exact mirror/checksum. An explicit raw redistribution license was not captured. | Attribute Kevin Hillstrom/MineThatData and the mirror. Readers obtain data from the linked source; do not rehost raw customer records or infer rights from a software/documentation license. |

Evidence: [captured REES46 metadata](../reports/source_terms/rees46_kaggle_metadata.json) and [Hillstrom source review](../reports/source_terms/hillstrom_source_review.json). The original Kaggle response is retained locally with its SHA-256. The provider period differs from this file: use the measured 2020-09-24–2021-02-28 UTC snapshot, not the provider's 2019/2020 description.

## Shareable project candidate

Code, SQL, written analysis, aggregate tables, figures, executed notebooks with aggregate outputs, input workbook and BI backup are separately inventoried. Do not include `data/raw`, `data/processed`, `data/work`, virtual environments, caches, node_modules or partial downloads. Recorded user/product identifiers remain local. No raw data, cloud report or GitHub repository is published by this QA step. The Power BI workspace report link requires the user's existing access; it is not a public link. PBIX is a local backup, not proof of Windows Desktop compatibility or automatic refresh.

The local aggregate portfolio and reproduction instructions can be reviewed without distributing source records. Raw-data redistribution remains outside the verified release scope. A new grant or source-specific license would need to be recorded before changing that scope. No blanket open-source license is applied to third-party data.

Primary sources: [REES46 provider](https://rees46.com/en/datasets), [exact Kaggle dataset](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-electronics-store), [Kaggle metadata endpoint](https://www.kaggle.com/api/v1/datasets/list?search=ecommerce-events-history-in-electronics-store), [Hillstrom author](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html), [TensorFlow catalog](https://www.tensorflow.org/datasets/catalog/hillstrom), [mirror loader](https://www.uplift-modeling.com/en/latest/_modules/sklift/datasets/datasets.html).
