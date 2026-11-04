"""GPU sanity check. Works on NVIDIA (CUDA) and AMD/LUMI (ROCm)."""

import torch


def main() -> None:
    if not torch.cuda.is_available():
        print(f"torch {torch.__version__} | NO GPU found (check NVIDIA driver: nvidia-smi)")
        return
    name = torch.cuda.get_device_name(0)
    mem = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"torch {torch.__version__} | GPU: {name} ({mem:.1f} GB) x{torch.cuda.device_count()}")
    x = torch.randn(4096, 4096, device="cuda")
    print("matmul ok:", tuple((x @ x).shape))


if __name__ == "__main__":
    main()
