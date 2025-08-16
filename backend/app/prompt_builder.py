from .schemas import FormDataIn
from .utils import hex_to_rgba

def build_prompt(data: FormDataIn, reference_image_url: str | None = None) -> dict:
    theme_value = data.customTheme.strip() if data.theme.lower() in ["özel", "ozel", "custom"] else data.theme

    colors_rgba = [hex_to_rgba(c.hex, c.alpha) for c in data.primaryColors]
    background_rgba = hex_to_rgba(data.backgroundColor.hex, data.backgroundColor.alpha)

    text_block = None
    if data.includeText and (data.text or "").strip():
        text_block = {
            "text": data.text.strip(),
            "font_family": data.fontFamily,
            "layout_hint": "safe-area, high-contrast, no-clipping"
        }

    prompt = {
        "goal": "Generate a single image based on structured constraints.",
        "aesthetics": {
            "theme": theme_value,
            "art_style": data.style,
        },
        "composition": {
            "aspect_ratio": data.aspectRatio,
            "background": background_rgba,
            "palette": colors_rgba
        },
        "overlays": {
            "include_text": bool(text_block),
            "text_block": text_block
        },
        "constraints": {
            "noise": "low",
            "consistency": "high",
            "lighting": "studio-balanced"
        },
        "references": {
            "image_url": reference_image_url
        },
        "output": {
            "format": "png",
            "safety": "standard"
        }
    }
    return prompt
