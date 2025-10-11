import torch
import trimesh

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
        return (image, mask, image)

import trimesh

class Hy3D21PostprocessMeshSimple:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trimesh": ("TRIMESH",),
                "remove_floaters": ("BOOLEAN", {"default": True}),
                "remove_degenerate_faces": ("BOOLEAN", {"default": True}),
                "reduce_faces": ("BOOLEAN", {"default": True}),
                "max_facenum": ("INT", {"default": 40000, "min": 1, "max": 10000000, "step": 1}),
                "smooth_normals": ("BOOLEAN", {"default": False}),
            },
        }
    
    RETURN_TYPES = ("TRIMESH",)
    RETURN_NAMES = ("trimesh",)
    FUNCTION = "process"
    CATEGORY = "Hunyuan3D21Wrapper"
    
    def process(self, trimesh, remove_floaters, remove_degenerate_faces, reduce_faces, max_facenum, smooth_normals):
        import trimesh as Trimesh  # For the smoothing module
        
        new_mesh = trimesh.copy()
        
        if remove_floaters:
            # Split mesh into connected components and keep only the largest
            components = new_mesh.split(only_watertight=False)
            if len(components) > 0:
                new_mesh = components[0]  # Largest component by default
                for component in components[1:]:
                    if len(component.faces) > len(new_mesh.faces):
                        new_mesh = component
            print(f"Removed floaters, resulting in {new_mesh.vertices.shape[0]} vertices and {new_mesh.faces.shape[0]} faces")
        
        if remove_degenerate_faces:
            # Remove degenerate faces (zero area, duplicate vertices, etc)
            new_mesh.remove_degenerate_faces()
            new_mesh.remove_duplicate_faces()
            new_mesh.remove_infinite_values()
            print(f"Removed degenerate faces, resulting in {new_mesh.vertices.shape[0]} vertices and {new_mesh.faces.shape[0]} faces")
        
        if reduce_faces:
            # Simplify mesh using quadric decimation
            if len(new_mesh.faces) > max_facenum:
                new_mesh = new_mesh.simplify_quadric_decimation(max_facenum)
            print(f"Reduced faces, resulting in {new_mesh.vertices.shape[0]} vertices and {new_mesh.faces.shape[0]} faces")
        
        if smooth_normals:
            # Smooth vertex normals
            new_mesh.vertex_normals = Trimesh.smoothing.get_vertices_normals(new_mesh)
        
        return (new_mesh,)

# Required exports
NODE_CLASS_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": Hy3D21ImageWithAlphaInput
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": "Image with Alpha Input (Hy3D21)"
}