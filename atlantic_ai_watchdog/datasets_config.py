"""
Dataset configuration for the AI Watchdog screener, for both tools (modes).

For each mode:
  datasets        - the exact dataset SLUGS the API uses (order = display order)
  needs_creator_id- music resolves a creatorId (MusicBrainz MBID) via autocomplete
                    before calling grouped; video keys off the search term alone
  status          - per-dataset flag, set from each dataset's "Learn more" page:
                      "USED_BY"         -> page says "has been used by <AI company>"
                      "DOWNLOADED_ONLY" -> only "has been downloaded by <universities>"
                      "UNKNOWN"         -> not yet classified (reported as
                                           PRESENT_UNCLASSIFIED)
  used_by         - optional list of the companies named on the page (for the
                    report). Purely informational.
  article         - the dataset's "Learn more" URL, for reference / re-checking.

>>> To finish: read each dataset's "Learn more" page and set status/used_by. <<<
The three video datasets below are PRE-FILLED from the page text you provided.
Everything marked UNKNOWN still needs a look.
"""

MODES = {
    "music": {
        "needs_creator_id": True,
        "datasets": [
            "free-music-archive",
            "laion-disco-12m",
            "sleeping-disco-9m",
            "spotify-tracks-dataset",
        ],
        "status": {
            # Confirmed by reading each dataset's article (2026-07-01):
            "free-music-archive":     "USED_BY",          # "used to train...by Google, and a subset by Stability AI"
            "spotify-tracks-dataset": "DOWNLOADED_ONLY",  # "downloaded more than 70,000 times" (no company named)
            "laion-disco-12m":        "ASSEMBLED_ONLY",   # only "assembled by LAION" (Stability appears re: LAION funding, not usage)
            "sleeping-disco-9m":      "ASSEMBLED_ONLY",   # only "assembled by Sleeping AI"
        },
        "used_by": {
            "free-music-archive": ["Google", "Stability AI"],
        },
        "wording": {
            "free-music-archive":     "A collection of 106,574 tracks downloaded from the Free Music Archive in 2016; assembled by École Polytechnique Fédérale de Lausanne. Most tracks are Creative Commons licensed, requiring credit and FORBIDDING commercial use. The dataset was used to train generative-AI models by Google, and a 13,874-track subset was used by Stability AI.",
            "spotify-tracks-dataset": "A collection of 114,000 tracks ripped from Spotify; assembled by an unknown AI developer on Hugging Face. It has been downloaded more than 70,000 times as of May 2026. (No company usage stated.)",
            "laion-disco-12m":        "A collection of 12,320,916 tracks from YouTube; assembled by LAION, a German nonprofit funded by Hugging Face and Stability AI's co-founder Emad Mostaque. (No company usage stated.)",
            "sleeping-disco-9m":      "A collection of 9,713,413 tracks from YouTube with lyrics from Genius.com; assembled by Sleeping AI. (No company usage stated.)",
        },
        "article": {
            "free-music-archive":     "https://www.theatlantic.com/technology/2026/06/dataset-free-music-archive/687336/",
            "laion-disco-12m":        "https://www.theatlantic.com/technology/2026/06/dataset-laion-disco-12m/687508/",
            "sleeping-disco-9m":      "https://www.theatlantic.com/technology/2026/06/dataset-sleeping-disco-9m/687509/",
            "spotify-tracks-dataset": "https://www.theatlantic.com/technology/2026/06/dataset-spotify/687510/",
        },
    },
    "video": {
        "needs_creator_id": False,   # grouped works with just the creator name
        "datasets": [
            "runway-jupiter",     # displayed "Runway Gen-3"
            "yttemporal-180m",
            "internvid",
            "panda70m",
            "hdvila100m",
            "koala36m",
            "howto100m",
            "hdvg130m",
            "openvid1m",
            "vidgen1m",
            "youtube8m",
        ],
        "status": {
            # Classified 2026-07-01 by reading each article directly:
            "runway-jupiter":  "USED_BY",          # Runway collected+trained Gen-3 (3,967 channels in internal doc)
            "yttemporal-180m": "USED_BY",          # used by Stability AI, ByteDance (for experimentation)
            "internvid":       "USED_BY",          # used by Stability AI, ByteDance
            "panda70m":        "ASSEMBLED_ONLY",   # "compiled by Snap" (no company usage stated)
            "hdvila100m":      "USED_BY",          # used by Meta, ByteDance, Snap, Tencent
            "koala36m":        "ASSEMBLED_ONLY",   # "compiled by Kuaishou" (refinement of Panda-70M)
            "howto100m":       "ASSEMBLED_ONLY",   # hosted by European research institutions; no company usage
            "hdvg130m":        "USED_BY",          # used by Nvidia (+ downloaded by 50+ universities)
            "openvid1m":       "USED_BY",          # used by Amazon, Microsoft, Nvidia, ByteDance, Kuaishou
            "vidgen1m":        "USED_BY",          # used by Amazon, Nvidia
            "youtube8m":       "UNKNOWN",          # Atlantic's article link (683947) is broken; unclassified
        },
        "used_by": {
            "runway-jupiter":  ["Runway"],
            "yttemporal-180m": ["Allen Institute for AI", "University of Washington"],  # trained Merlot; hosted by Google
            "internvid":       ["Stability AI", "ByteDance"],
            "hdvila100m":      ["Meta", "ByteDance", "Snap", "Tencent"],
            "hdvg130m":        ["Nvidia"],
            "openvid1m":       ["Amazon", "Microsoft", "Nvidia", "ByteDance", "Kuaishou"],
            "vidgen1m":        ["Amazon", "Nvidia"],
        },
        "wording": {
            "runway-jupiter":  "Runway AI collected YouTube videos to train a video-generating AI model released as Gen-3 in 2024. An internal company document obtained by 404 Media lists 3,967 YouTube channels Runway identified as sources of high-quality video for training.",
            "yttemporal-180m": "Compiled by a team of researchers at the University of Washington and the Allen Institute for AI to train a multimodal model called Merlot, released 2021. Hosted by Google; downloaded more than 1,200 times.",
            "internvid":       "Compiled by OpenGVLab (Shanghai AI Laboratory), 2023. Hosted on Hugging Face, downloaded more than 3,200 times. It has been used by Stability AI and ByteDance for experimentation.",
            "panda70m":        "Compiled by Snap, released 2024. (No company usage stated.)",
            "hdvila100m":      "Compiled by Microsoft Research Asia, 2021, for the purpose of training video-based AI models. It has been used by Meta, ByteDance, Snap, and Tencent.",
            "koala36m":        "Compiled by Kuaishou Technology, 2024; a refinement of Snap's Panda-70M. Hosted on Hugging Face. (No company usage stated.)",
            "howto100m":       "Hosted on a website of the European research institutions that created it. (No company usage stated.)",
            "hdvg130m":        "Compiled by Microsoft, 2023, for the purpose of training video-generating AI models. The data set has been used by Nvidia; developers claim it has been downloaded by more than 50 universities and research institutes.",
            "openvid1m":       "Compiled by researchers at ByteDance (TikTok's parent), 2024. It has been used in experimental contexts, at least, by Amazon, Microsoft, Nvidia, ByteDance, Kuaishou, and others, and has been downloaded more than 380,000 times.",
            "vidgen1m":        "Created by researchers at the Shanghai Academy of AI for Science and Fudan University, 2024; built from Microsoft's HD-VILA-100M. This data set has been used by Amazon and Nvidia.",
            "youtube8m":       "(The Atlantic's article link is broken; unclassified. YouTube-8M is Google's 2016 dataset.)",
        },
        "article": {
            "runway-jupiter":  "https://www.theatlantic.com/technology/archive/2024/01/dataset-runway-gen-3/684045/",
            "yttemporal-180m": "https://www.theatlantic.com/technology/archive/2025/09/dataset-yt-temporal-180m/683937/",
            "internvid":       "https://www.theatlantic.com/technology/archive/2024/01/dataset-internvid/683871/",
            "panda70m":        "https://www.theatlantic.com/technology/archive/2024/01/dataset-panda-70m/683869/",
            "hdvila100m":      "https://www.theatlantic.com/technology/archive/2024/01/dataset-hd-vila-100m/683936/",
            "koala36m":        "https://www.theatlantic.com/technology/archive/2024/01/dataset-koala-36m/683870/",
            "howto100m":       "https://www.theatlantic.com/technology/archive/2024/01/dataset-howto100m/683943/",
            "hdvg130m":        "https://www.theatlantic.com/technology/archive/2024/01/dataset-hd-vg-130m/683872/",
            "openvid1m":       "https://www.theatlantic.com/technology/archive/2024/01/dataset-openvid-1m/683939/",
            "vidgen1m":        "https://www.theatlantic.com/technology/archive/2024/01/dataset-vidgen-1m/683940/",
            "youtube8m":       "https://www.theatlantic.com/technology/archive/2024/01/dataset-youtube8m/683947/",
        },
    },
}
