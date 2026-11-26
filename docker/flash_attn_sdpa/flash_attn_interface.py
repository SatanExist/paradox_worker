import torch.nn.functional as F


def flash_attn_func(q, k, v, dropout_p=0.0, softmax_scale=None, causal=False, **kwargs):
    # flash-attn layout (B, L, H, D) -> SDPA (B, H, L, D) and back
    dt = q.dtype
    out = F.scaled_dot_product_attention(q.transpose(1, 2), k.to(dt).transpose(1, 2), v.to(dt).transpose(1, 2),
                                         dropout_p=dropout_p, is_causal=causal, scale=softmax_scale)
    return out.transpose(1, 2)
