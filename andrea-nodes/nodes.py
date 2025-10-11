import torch

class Hy3D21ImageWithAlphaInput:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),
            },
        }
    
    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("image", "mask", "image_with_alpha")
    FUNCTION = "process_image"
    CATEGORY = "Hunyuan3D21Wrapper"
    
    def process_image(self, image, mask):
        """
        image: [B, H, W, C] - RGB tensor
        mask: [B, H, W] - mask tensor
        """
        # Convert mask to alpha channel (invert it back)
        alpha = 1.0 - mask
        
        # Ensure alpha has the right shape [B, H, W, 1]
        if alpha.dim() == 3:
            alpha = alpha.unsqueeze(-1)
        
        # Combine image (RGB) with alpha channel to create RGBA
        image_with_alpha = torch.cat([image, alpha], dim=-1)
        
        return (image, mask, image_with_alpha)

# Required exports
NODE_CLASS_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": Hy3D21ImageWithAlphaInput
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": "Image with Alpha Input (Hy3D21)"
}