from PIL import Image
import torch
import numpy as np
from transparent_background import Remover
from tqdm import tqdm


# Tensor to PIL
def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

# Convert PIL to Tensor
def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

class InspyrenetRembg:
    _cached_remover = None
    _cached_jit_mode = None

    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit):
        # Only load if not cached or if jit mode changed
        if (InspyrenetRembg._cached_remover is None or 
            InspyrenetRembg._cached_jit_mode != torchscript_jit):
            
            print(f"🔥 Loading InspyreNet Remover (jit={torchscript_jit})")
            
            if torchscript_jit == "default":
                remover = Remover()
            else:
                remover = Remover(jit=True)
            
            InspyrenetRembg._cached_remover = remover
            InspyrenetRembg._cached_jit_mode = torchscript_jit
        else:
            print("⚡ Using cached InspyreNet Remover")
            remover = InspyrenetRembg._cached_remover
        
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba')
            out = pil2tensor(mid)
            img_list.append(out)
        
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)

        
class InspyrenetRembgAdvanced:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit, threshold):
        if (torchscript_jit == "default"):
            remover = Remover()
        else:
            remover = Remover(jit=True)
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba', threshold=threshold)
            out =  pil2tensor(mid)
            img_list.append(out)
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)