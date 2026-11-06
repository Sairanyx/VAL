# viktortrilar: main
**Goal:** my plan tasks: scene loading, cleaning, rendered views, own splat, then splitting objects
**Done:** app/scene (loader, cleaning, cameras, render), scripts/views_archive.py and `make views`. 700 views packed to ~/Downloads/equipment_room_views_v1.tar (687 MB, SHA-256 starts 98368c60) and unpacked to data/scene/equipment_room
**Verified:** ruff and pytest pass with numpy, no torch tests. Archive hash matches Roihu's, 700 images and 700 depth maps unpacked. `make views` Release path untested, as the Release isn't uploaded
**Roihu:** views also in `sinceai/data/scene/equipment_room`. COLMAP job 2920828 at 1,428 of 1,500 frames at last check; log `sinceai/logs/colmap-2920828.out`. Project at 225.7 of 250 GB after deleting `inspection/nm_trial_1553688/*/frames` with Viktor's approval. Cert valid to 2026-11-07 20:41; pass it with `-o CertificateFile=`
**Next:** Viktor uploads the archive to Drive and the `views-v1` Release; check COLMAP; lighter tablet scene and rough clustering split for Benjamin
**Blockers:** GitHub's `gh` isn't installed here (the one in .venv is an unrelated PyPI package). Open: whether Valmet wants Moving Atoms used
