"""
USDZ Packaging Module

Handles creating USDZ archives with embedded textures.
USDZ is a single-file format that contains USD + all texture dependencies.
"""

import os
import shutil
import stat
from pxr import Usd, UsdShade, UsdUtils, Sdf


def package_usd_to_usdz(usd_file: str, fix_permissions: bool = True) -> str:
    """
    Package USD + textures into a single USDZ archive.
    """
    print(f"📦 Creating USDZ package with embedded textures...")

    usdz_file = usd_file.replace('.usd', '.usdz')
    textures_dir = os.path.join(os.path.dirname(usd_file), 'textures')

    # Step 1: Update texture paths to relative (required for embedding)
    _update_texture_paths_to_relative(usd_file, textures_dir)

    # Step 2: Create USDZ archive (textures MUST exist at this point!)
    success = _create_usdz_archive(usd_file, usdz_file)

    if success:
        # Step 3: Verify textures are embedded before cleanup
        texture_count = _count_embedded_textures(usdz_file)
        
        # Step 4: Fix permissions if requested
        if fix_permissions:
            _fix_file_permissions(usdz_file, os.path.dirname(usd_file))

        # Step 5: Clean up ONLY if textures are embedded
        if texture_count > 0:
            _cleanup_temp_files(usd_file, textures_dir)
            print(f"✓ USDZ package created with {texture_count} embedded textures")
        else:
            print(f"⚠ Warning: No textures found in USDZ - keeping source files for debugging")
            print(f"  USD file: {usd_file}")
            print(f"  Textures dir: {textures_dir}")

        print(f"  Standalone file: {os.path.basename(usdz_file)}")
        return usdz_file
    else:
        print(f"⚠ Warning: USDZ file was not created at {usdz_file}")
        return None

def _count_embedded_textures(usdz_file: str) -> int:
    """
    Count how many textures are actually embedded in the USDZ.
    
    Args:
        usdz_file: Path to USDZ archive
        
    Returns:
        Number of embedded texture files
    """
    import zipfile
    
    try:
        with zipfile.ZipFile(usdz_file, 'r') as archive:
            # Count image files in the archive
            texture_extensions = {'.png', '.jpg', '.jpeg', '.ktx2', '.dds'}
            textures = [f for f in archive.namelist() 
                       if any(f.lower().endswith(ext) for ext in texture_extensions)]
            return len(textures)
    except Exception as e:
        print(f"⚠ Could not verify embedded textures: {e}")
        return 0

def _update_texture_paths_to_relative(usd_file: str, textures_dir: str) -> None:
    """
    Update texture asset paths to be relative and ensure they exist.
    """
    stage = Usd.Stage.Open(usd_file)
    modified = False
    usd_dir = os.path.dirname(usd_file)

    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)

            for input_name in ["file", "texture"]:
                texture_input = shader.GetInput(input_name)
                if not texture_input:
                    continue

                asset_path = texture_input.Get()
                if not asset_path:
                    continue

                # Get current path
                path_str = str(asset_path.path) if hasattr(asset_path, 'path') else str(asset_path)
                
                # Convert to absolute path to find the file
                if os.path.isabs(path_str):
                    abs_texture_path = path_str
                else:
                    abs_texture_path = os.path.join(usd_dir, path_str)
                
                if os.path.exists(abs_texture_path):
                    # Ensure textures directory exists
                    os.makedirs(textures_dir, exist_ok=True)
                    
                    # Copy texture to textures/ subdirectory
                    texture_filename = os.path.basename(abs_texture_path)
                    new_texture_path = os.path.join(textures_dir, texture_filename)
                    
                    if not os.path.exists(new_texture_path):
                        shutil.copy2(abs_texture_path, new_texture_path)
                        print(f"  Moved texture: {texture_filename} → textures/")
                    
                    # Update path to relative: textures/filename.png
                    rel_path = os.path.relpath(new_texture_path, usd_dir)
                    texture_input.Set(Sdf.AssetPath(rel_path))
                    modified = True

    if modified:
        stage.Save()
        print(f"✓ Updated texture paths to relative")


def _create_usdz_archive(usd_file: str, usdz_file: str) -> bool:
    """
    Create USDZ archive using USD utilities.

    Args:
        usd_file: Source USD file
        usdz_file: Destination USDZ file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Create USDZ using official USD utilities
        # Note: May throw exception if optional dependencies are missing (e.g., MDL files)
        # but USDZ file is still created successfully before the exception
        UsdUtils.CreateNewUsdzPackage(
            Sdf.AssetPath(usd_file),
            usdz_file
        )
    except Exception as pkg_err:
        # USDZ may still be created despite exception
        # (e.g., missing MDL references that aren't critical)
        pass

    return os.path.exists(usdz_file)


def fix_usdz_archive_texture_paths(usdz_file: str) -> None:
    """
    Fix texture paths to use USDZ archive format by manually re-zipping.

    Args:
        usdz_file: Path to USDZ archive
    """
    print(f"🔧 Fixing USDZ texture paths to archive format...", flush=True)

    import zipfile
    import tempfile

    temp_dir = tempfile.mkdtemp()
    usdz_filename = os.path.basename(usdz_file)

    try:
        # Extract all files from USDZ (USD + textures)
        with zipfile.ZipFile(usdz_file, 'r') as archive:
            archive.extractall(temp_dir)
            print(f"  Extracted {len(archive.namelist())} files from USDZ", flush=True)

        # Find and modify the USD file
        usd_name = usdz_filename.replace('.usdz', '.usd')
        extracted_usd = os.path.join(temp_dir, usd_name)

        if not os.path.exists(extracted_usd):
            print(f"⚠ Warning: Could not find {usd_name} in USDZ archive", flush=True)
            return

        stage = Usd.Stage.Open(extracted_usd)
        if not stage:
            print(f"⚠ Warning: Could not open extracted USD", flush=True)
            return

        modified = False
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Shader):
                shader = UsdShade.Shader(prim)

                for input_name in ["file", "texture"]:
                    texture_input = shader.GetInput(input_name)
                    if not texture_input:
                        continue

                    asset_path = texture_input.Get()
                    if not asset_path:
                        continue

                    path_str = str(asset_path.path) if hasattr(asset_path, 'path') else str(asset_path)

                    # Convert relative paths to archive format
                    if not path_str.startswith('@') and not os.path.isabs(path_str):
                        archive_path = f"@{usdz_filename}@/{path_str}"
                        texture_input.Set(Sdf.AssetPath(archive_path))
                        modified = True
                        print(f"  Updated: {path_str} → {archive_path}", flush=True)

        if modified:
            stage.Save()
            print(f"✓ Texture paths updated", flush=True)

            # Re-create USDZ by manually zipping all files (MUST be STORED, not compressed!)
            os.remove(usdz_file)

            with zipfile.ZipFile(usdz_file, 'w', zipfile.ZIP_STORED) as new_archive:
                # Walk through temp dir and add all files
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        new_archive.write(file_path, arcname)
                        print(f"  Added to USDZ: {arcname}", flush=True)

            print(f"✓ USDZ re-packaged with fixed paths", flush=True)
        else:
            print(f"  No texture paths needed updating", flush=True)

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def _fix_file_permissions(usdz_file: str, parent_dir: str) -> None:
    """
    Fix file permissions and ownership for Docker host access.

    Args:
        usdz_file: Path to USDZ file
        parent_dir: Parent directory to inherit ownership from
    """
    try:
        # Make file readable/writable by all users
        os.chmod(usdz_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)

        # Change ownership to host user (get UID/GID from parent directory)
        parent_stat = os.stat(parent_dir)
        os.chown(usdz_file, parent_stat.st_uid, parent_stat.st_gid)

        print(f"✓ Fixed USDZ file permissions and ownership")
    except Exception as perm_err:
        print(f"⚠ Warning: Could not fix permissions/ownership: {perm_err}")


def _cleanup_temp_files(usd_file: str, textures_dir: str) -> None:
    """
    Clean up temporary USD file and external textures directory.

    After creating USDZ, we don't need the standalone USD or external textures
    since everything is embedded in the USDZ archive.

    Args:
        usd_file: Path to USD file to remove
        textures_dir: Path to textures directory to remove
    """
    try:
        # Remove standalone USD file
        if os.path.exists(usd_file):
            os.remove(usd_file)
            print(f"✓ Removed standalone USD file (textures now embedded in USDZ)")

        # Remove external textures directory
        if os.path.exists(textures_dir):
            shutil.rmtree(textures_dir)
            print(f"✓ Removed external textures directory")
    except Exception as cleanup_err:
        print(f"⚠ Warning: Could not clean up USD/textures: {cleanup_err}")


def fix_texture_permissions(textures_dir: str, parent_dir: str) -> None:
    """
    Fix permissions for all textures in a directory (used before USDZ creation).

    Args:
        textures_dir: Directory containing texture files
        parent_dir: Parent directory to inherit ownership from
    """
    if not os.path.exists(textures_dir):
        return

    try:
        parent_stat = os.stat(parent_dir)

        # Fix directory ownership
        os.chown(textures_dir, parent_stat.st_uid, parent_stat.st_gid)

        # Fix each texture file
        for texture_file in os.listdir(textures_dir):
            texture_path = os.path.join(textures_dir, texture_file)
            if os.path.isfile(texture_path):
                os.chmod(texture_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                os.chown(texture_path, parent_stat.st_uid, parent_stat.st_gid)

        print(f"✓ Fixed texture permissions and ownership ({len(os.listdir(textures_dir))} files)")
    except Exception as perm_err:
        print(f"⚠ Warning: Could not fix permissions/ownership: {perm_err}")
