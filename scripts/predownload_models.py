"""Download lightweight base models BEFORE the event (venue Wi-Fi is shared).
All of these fine-tune comfortably on a 6 GB laptop GPU (RTX 4050).
Comment out what you don't need.   make models"""

from huggingface_hub import snapshot_download

MODELS = [
    # --- text: classification / NER / regression (fine-tune) ---
    "distilbert/distilbert-base-uncased",  # 66M, English, fastest to train
    "FacebookAI/xlm-roberta-base",  # 280M, multilingual incl. Finnish
    "TurkuNLP/bert-base-finnish-cased-v1",  # 110M, Finnish BERT (from Turku!)
    # --- text: embeddings / similarity ---
    "sentence-transformers/all-MiniLM-L6-v2",  # 22M, fast embeddings
    "intfloat/multilingual-e5-small",  # 118M, multilingual embeddings
    # --- vision (fine-tune) ---
    "timm/resnet18.a1_in1k",  # 11M, classic baseline
    "timm/efficientnet_b0.ra_in1k",  # 5M, small + accurate
    "timm/convnext_tiny.fb_in22k_ft_in1k",  # 28M, strong modern CNN
    "google/vit-base-patch16-224",  # 86M, vision transformer
    # --- audio ---
    "openai/whisper-tiny",  # 39M speech-to-text
    # --- small LLMs (LoRA fine-tune / run offline) ---
    "HuggingFaceTB/SmolLM2-135M-Instruct",  # 135M, trains in minutes
    "Qwen/Qwen2.5-0.5B-Instruct",  # 0.5B, good quality for size
    # "Qwen/Qwen2.5-1.5B-Instruct",          # 1.5B, LoRA fits in 6 GB
]

for m in MODELS:
    print("->", m)
    snapshot_download(m)
print("done; cached in ~/.cache/huggingface")
