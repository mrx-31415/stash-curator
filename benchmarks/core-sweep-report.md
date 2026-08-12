# Core GOMAXPROCS sweep

- date: 2026-08-12 12:08:55 UTC
- host: johan-Standard-PC-i440FX-PIIX-1996
- corpus: {'seed': 124, 'n_scenes': 24000, 'n_tags': 8000, 'n_performers': 10000, 'known_performers': 200}
- determinism: OK (1 identical build outputs)

## Wall time scaling

| GOMAXPROCS | reps | median wall (ms) | min | max | median peak RSS (kB) |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 301720.1 | 262027.5 | 341412.7 | 4477752.0 |
| 2 | 2 | 209959.2 | 206553.3 | 213365.1 | 4139542.0 |
| 4 | 2 | 201175.3 | 200648.3 | 201702.4 | 3972196.0 |
| 8 | 2 | 195718.8 | 194876.6 | 196561.0 | 4073708.0 |

## Per-stage timings (median ms by GOMAXPROCS)

| stage | 1 | 2 | 4 | 8 |
| --- | --- | --- | --- | --- |
| affinities | 23978.5 | 14781.0 | 14784.5 | 13717.0 |
| cleanup | 0.0 | 0.0 | 0.0 | 0.0 |
| database_writing | 16640.0 | 10146.0 | 9864.0 | 9736.5 |
| feature_build | 19024.0 | 10035.5 | 8830.0 | 9482.5 |
| feature_database_writing | 48186.0 | 40427.5 | 42856.0 | 40867.0 |
| feature_indexing | 9683.0 | 6486.5 | 5520.0 | 4895.5 |
| feature_lookup | 5797.0 | 2254.5 | 2136.5 | 2576.0 |
| feature_publication | 92.0 | 65.5 | 89.0 | 78.5 |
| feature_total | 87846.0 | 62680.5 | 62443.5 | 61356.5 |
| feature_validation | 2345.0 | 1324.5 | 1800.5 | 1735.5 |
| indexing | 44697.0 | 31606.5 | 29597.5 | 30527.5 |
| labels | 180.5 | 78.5 | 88.0 | 86.0 |
| lane_classification | 9822.5 | 8810.5 | 8168.0 | 7639.5 |
| publication | 39.5 | 27.0 | 35.5 | 28.0 |
| reason_generation | 0.0 | 0.0 | 0.0 | 0.0 |
| score_first_ordering | 0.0 | 0.0 | 0.0 | 0.0 |
| scoring | 18969.0 | 10543.0 | 8083.0 | 7335.5 |
| similarity | 108597.5 | 79568.0 | 75746.5 | 72377.0 |
| sqlite_index_creation | 215.5 | 175.5 | 214.0 | 155.0 |
| total | 301174.5 | 209559.5 | 200802.5 | 195315.0 |
| validation | 4.0 | 2.0 | 2.5 | 2.0 |
| varied_ordering | 34657.5 | 22619.5 | 21215.0 | 22732.5 |

## Per-stage peak RSS (median kB by GOMAXPROCS)

| stage | 1 | 2 | 4 | 8 |
| --- | --- | --- | --- | --- |
| affinities | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| cleanup | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| database_writing | 4042564.0 | 3494744.0 | 3484046.0 | 3530756.0 |
| feature_build | 2017624.0 | 1962160.0 | 1751072.0 | 1755148.0 |
| feature_database_writing | 2819770.0 | 2625290.0 | 2457206.0 | 2312696.0 |
| feature_indexing | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| feature_lookup | 276924.0 | 276924.0 | 276924.0 | 276924.0 |
| feature_publication | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| feature_total | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| feature_validation | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| indexing | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| labels | 2870422.0 | 2625290.0 | 2522742.0 | 2443768.0 |
| lane_classification | 4106180.0 | 3741336.0 | 3562062.0 | 3617540.0 |
| publication | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| reason_generation | 4474616.0 | 4136790.0 | 3969252.0 | 4070956.0 |
| score_first_ordering | 4106180.0 | 3741336.0 | 3562062.0 | 3617540.0 |
| scoring | 2917982.0 | 2625290.0 | 2571224.0 | 2635224.0 |
| similarity | 2917982.0 | 2625290.0 | 2571224.0 | 2635224.0 |
| sqlite_index_creation | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| total | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| validation | 4477752.0 | 4139542.0 | 3972196.0 | 4073708.0 |
| varied_ordering | 4474616.0 | 4136790.0 | 3969252.0 | 4070956.0 |

## Build outputs (determinism check)

| GOMAXPROCS | rep | model_id | scene_count | peak RSS (kB) |
| --- | --- | --- | --- | --- |
| 1 | 0 | model-9db80735bbb7422d9379 | 24000 | 4331700 |
| 1 | 1 | model-9db80735bbb7422d9379 | 24000 | 4623804 |
| 2 | 0 | model-9db80735bbb7422d9379 | 24000 | 4117896 |
| 2 | 1 | model-9db80735bbb7422d9379 | 24000 | 4161188 |
| 4 | 0 | model-9db80735bbb7422d9379 | 24000 | 3972016 |
| 4 | 1 | model-9db80735bbb7422d9379 | 24000 | 3972376 |
| 8 | 0 | model-9db80735bbb7422d9379 | 24000 | 4013148 |
| 8 | 1 | model-9db80735bbb7422d9379 | 24000 | 4134268 |
