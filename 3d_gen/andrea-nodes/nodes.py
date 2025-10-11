import torch
import trimesh
import os
import gc
import numpy as np
import folder_paths
from PIL import Image
import comfy.model_management as mm
import trimesh as Trimesh

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

def reducefacesnano(new_mesh, max_facenum):
    try:
        import pynanoinstantmeshes as PyNIM
        
        current_faces = len(new_mesh.faces)
        
        target_vertices = max(100, int(max_facenum * 0.25))
        
        print(f"Remeshing from {current_faces} faces to ~{max_facenum} target faces...")
        print(f"Requesting {target_vertices} vertices from Instant Meshes...")
        
        # Remesh with Instant Meshes
        new_verts, new_faces = PyNIM.remesh(
            np.array(new_mesh.vertices, dtype=np.float32),
            np.array(new_mesh.faces, dtype=np.uint32),
            target_vertices,
            align_to_boundaries=True,
            smooth_iter=2
        )
        
        # Instant Meshes can fail, check validity
        if new_verts.shape[0] - 1 != new_faces.max():
            raise ValueError("Remeshing failed")
        
        # Triangulate quads (Instant Meshes outputs quads)
        new_faces = Trimesh.geometry.triangulate_quads(new_faces)
        
        new_mesh = Trimesh.Trimesh(vertices=new_verts.astype(np.float32), faces=new_faces)
        
        print(f"Remeshed, resulting in {new_mesh.vertices.shape[0]} vertices and {new_mesh.faces.shape[0]} faces")
        return new_mesh
    except Exception as e:
        print(f"Instant Meshes failed: {e}, skipping face reduction")
        return new_mesh  # Add this line to return original mesh on failure

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
            new_mesh = reducefacesnano(new_mesh, max_facenum)
            print(f"Reduced faces, resulting in {new_mesh.vertices.shape[0]} vertices and {new_mesh.faces.shape[0]} faces")
        
        if smooth_normals:
            # Smooth vertex normals
            new_mesh.vertex_normals = Trimesh.smoothing.get_vertices_normals(new_mesh)
        
        return (new_mesh,)

class MeshGen3D:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": (folder_paths.get_filename_list("diffusion_models"), {"tooltip": "These models are loaded from the 'ComfyUI/models/diffusion_models' -folder"}),
                "image": ("IMAGE", {"tooltip": "Image to generate mesh from"}),
                "steps": ("INT", {"default": 50, "min": 1, "max": 100, "step": 1, "tooltip": "Number of diffusion steps"}),
                "guidance_scale": ("FLOAT", {"default": 5.0, "min": 1, "max": 30, "step": 0.1, "tooltip": "Guidance scale"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "attention_mode": (["sdpa", "sageattn"], {"default": "sdpa"}),
            },
        }

    RETURN_TYPES = ("HY3DLATENT",)
    RETURN_NAMES = ("latents",)
    FUNCTION = "loadmodel"
    CATEGORY = "Hunyuan3D21Wrapper"

    def loadmodel(self, model, image, steps, guidance_scale, seed, attention_mode):
        device = mm.get_torch_device()
        
        seed = seed % (2**32)

        model_path = folder_paths.get_full_path("diffusion_models", model)
        
        pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_single_file(
            config_path=os.path.join(script_directory, 'configs', 'dit_config_2_1.yaml'),
            ckpt_path=model_path,
            offload_device=device,
            attention_mode=attention_mode)
                    
        image = tensor2pil(image)
        
        latents = pipeline(
            image=image,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=torch.manual_seed(seed)
            )
        
        gc.collect()            
        
        return (latents,)

# Required exports
NODE_CLASS_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": Hy3D21ImageWithAlphaInput,
    "Hy3D21PostprocessMeshSimple": Hy3D21PostprocessMeshSimple,
    "MeshGen3D": MeshGen3D
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Hy3D21ImageWithAlphaInput": "Image with Alpha Input (Hy3D21)",
    "Hy3D21PostprocessMeshSimple": "PostProcessAndrea",
    "MeshGen3D": "MeshGen3D"
}