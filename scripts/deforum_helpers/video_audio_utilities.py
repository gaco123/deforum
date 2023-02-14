import os
import cv2
import shutil
import math
import requests
import subprocess
import time
from pkg_resources import resource_filename
from modules.shared import state
from .general_utils import checksum, duplicate_pngs_from_folder
# move these from here?
from .rich import console

# e.g gets 'x2' returns just 2 as int
def extract_number(string):
    return int(string[1:]) if len(string) > 1 and string[1:].isdigit() else -1
    
def vid2frames(video_path, video_in_frame_path, n=1, overwrite=True, extract_from_frame=0, extract_to_frame=-1, out_img_format='jpg', numeric_files_output = False): 
    if (extract_to_frame <= extract_from_frame) and extract_to_frame != -1:
        raise RuntimeError('Error: extract_to_frame can not be higher than extract_from_frame')
    
    if n < 1: n = 1 #HACK Gradio interface does not currently allow min/max in gr.Number(...) 

    # check vid path using a function and only enter if we get True
    if is_vid_path_valid(video_path):
        
        name = get_frame_name(video_path)
        
        vidcap = cv2.VideoCapture(video_path)
        video_fps = vidcap.get(cv2.CAP_PROP_FPS)

        input_content = []
        if os.path.exists(video_in_frame_path) :
            input_content = os.listdir(video_in_frame_path)

        # check if existing frame is the same video, if not we need to erase it and repopulate
        if len(input_content) > 0:
            #get the name of the existing frame
            content_name = get_frame_name(input_content[0])
            if not content_name.startswith(name):
                overwrite = True

        # grab the frame count to check against existing directory len 
        frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT)) 
        
        # raise error if the user wants to skip more frames than exist
        if n >= frame_count : 
            raise RuntimeError('Skipping more frames than input video contains. extract_nth_frames larger than input frames')
        
        expected_frame_count = math.ceil(frame_count / n) 
        # Check to see if the frame count is matches the number of files in path
        if overwrite or expected_frame_count != len(input_content):
            shutil.rmtree(video_in_frame_path)
            os.makedirs(video_in_frame_path, exist_ok=True) # just deleted the folder so we need to make it again
            input_content = os.listdir(video_in_frame_path)
        
        print(f"Trying to extract frames from video with input FPS of {video_fps}. Please wait patiently.")
        if len(input_content) == 0:
            vidcap.set(cv2.CAP_PROP_POS_FRAMES, extract_from_frame) # Set the starting frame
            success,image = vidcap.read()
            count = extract_from_frame
            t=1
            success = True
            while success:
                if state.interrupted:
                    return
                if (count <= extract_to_frame or extract_to_frame == -1) and count % n == 0:
                    if numeric_files_output == True:
                        cv2.imwrite(video_in_frame_path + os.path.sep + f"{t:05}.{out_img_format}" , image) # save frame as file
                    else:
                        cv2.imwrite(video_in_frame_path + os.path.sep + name + f"{t:05}.{out_img_format}" , image) # save frame as file
                    t += 1
                success,image = vidcap.read()
                count += 1
            print(f"Successfully extracted {count} frames from video.")
        else:
            print("Frames already unpacked")
        vidcap.release()
        return video_fps

# make sure the video_path provided is an existing local file or a web URL with a supported file extension
def is_vid_path_valid(video_path):
    # make sure file format is supported!
    file_formats = ["mov", "mpeg", "mp4", "m4v", "avi", "mpg", "webm"]
    extension = video_path.rsplit('.', 1)[-1].lower()
    # vid path is actually a URL, check it 
    if video_path.startswith('http://') or video_path.startswith('https://'):
        response = requests.head(video_path, allow_redirects=True)
        if response.status_code == 404:
            raise ConnectionError("Video URL is not valid. Response status code: {}".format(response.status_code))
        elif response.status_code == 302:
            response = requests.head(response.headers['location'], allow_redirects=True)
        if response.status_code != 200:
            raise ConnectionError("Video URL is not valid. Response status code: {}".format(response.status_code))
        if extension not in file_formats:
            raise ValueError("Video file format '{}' not supported. Supported formats are: {}".format(extension, file_formats))
    else:
        if not os.path.exists(video_path):
            raise RuntimeError("Video path does not exist.")
        if extension not in file_formats:
            raise ValueError("Video file format '{}' not supported. Supported formats are: {}".format(extension, file_formats))
    return True

# quick-retreive frame count, FPS and H/W dimensions of a video (local or URL-based)
def get_quick_vid_info(vid_path):
    vidcap = cv2.VideoCapture(vid_path)
    video_fps = vidcap.get(cv2.CAP_PROP_FPS)
    video_frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT)) 
    video_width = int(vidcap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(vidcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vidcap.release()
    if video_fps.is_integer():
        video_fps = int(video_fps)

    return video_fps, video_frame_count, (video_width, video_height)
    
# Stitch images to a h264 mp4 video using ffmpeg
def ffmpeg_stitch_video(ffmpeg_location=None, fps=None, outmp4_path=None, stitch_from_frame=0, stitch_to_frame=None, imgs_path=None, add_soundtrack=None, audio_path=None, crf=17, preset='veryslow'):
    start_time = time.time()

    print(f"\033[0;33mStitching *video* from frames using FFmpeg:\n\033[0m{imgs_path}\nTo Video:\n{outmp4_path}")
    if stitch_to_frame == -1:
        stitch_to_frame = 9999999
    try:
        cmd = [
            ffmpeg_location,
            '-y',
            '-vcodec', 'png',
            '-r', str(int(fps)),
            '-start_number', str(stitch_from_frame),
            '-i', imgs_path,
            '-frames:v', str(stitch_to_frame),
            '-c:v', 'libx264',
            '-vf',
            f'fps={int(fps)}',
            '-pix_fmt', 'yuv420p',
            '-crf', str(crf),
            '-preset', preset,
            '-pattern_type', 'sequence',
            outmp4_path
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
    except FileNotFoundError:
        raise FileNotFoundError("FFmpeg not found. Please make sure you have a working ffmpeg path under 'ffmpeg_location' parameter.")
    except Exception as e:
        raise Exception(f'Error stitching frames to video. Actual runtime error:{e}')

    if add_soundtrack != 'None':
        print("Adding audio to video...")
        audio_add_start_time = time.time()
        try:
            cmd = [
                ffmpeg_location,
                '-i',
                outmp4_path,
                '-i',
                audio_path,
                '-map', '0:v',
                '-map', '1:a',
                '-c:v', 'copy',
                '-shortest',
                outmp4_path+'.temp.mp4'
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                print(stderr)
                raise RuntimeError(stderr)
            os.replace(outmp4_path+'.temp.mp4', outmp4_path)
            print(f"Adding audio to video took {time.time() - audio_add_start_time:.2f} seconds.")
            # print(f"FFmpeg Video+Audio stitching done in {time.time() - start_time:.2f} seconds!")
            print(f"\rFFmpeg Video+Audio stitching \033[0;32mdone\033[0m in {time.time() - start_time:.2f} seconds!")
        except Exception as e:
            print(f'Error adding audio to video. Actual error: {e}')
            # print(f"FFMPEG Video (sorry, no audio) stitching done in {time.time() - start_time:.2f} seconds!")
            print(f"FFMPEG Video (sorry, no audio) stitching \033[33mdone\033[0m in {time.time() - start_time:.2f} seconds!")
    else:
        # print(f"Video stitching done in {time.time() - start_time:.2f} seconds!")
        print(f"\rVideo stitching \033[0;32mdone\033[0m in {time.time() - start_time:.2f} seconds!")
        

def get_frame_name(path):
    name = os.path.basename(path)
    name = os.path.splitext(name)[0]
    return name
    
def get_next_frame(outdir, video_path, frame_idx, mask=False):
    frame_path = 'inputframes'
    if (mask): frame_path = 'maskframes'
    return os.path.join(outdir, frame_path, get_frame_name(video_path) + f"{frame_idx+1:05}.jpg")
     
def find_ffmpeg_binary():
    try:
        import google.colab
        return 'ffmpeg'
    except:
        pass
    for package in ['imageio_ffmpeg', 'imageio-ffmpeg']:
        try:
            package_path = resource_filename(package, 'binaries')
            files = [os.path.join(package_path, f) for f in os.listdir(package_path) if f.startswith("ffmpeg-")]
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0] if files else 'ffmpeg'
        except:
            return 'ffmpeg'
            
# These 2 functions belong to "stitch frames to video" in Output tab
def get_manual_frame_to_vid_output_path(input_path):
    root, ext = os.path.splitext(input_path)
    base, _ = root.rsplit("_", 1)
    output_path = f"{base}.mp4"
    i = 1
    while os.path.exists(output_path):
        output_path = f"{base}_{i}.mp4"
        i += 1
    return output_path
    
def direct_stitch_vid_from_frames(image_path, fps, f_location, f_crf, f_preset, add_soundtrack, audio_path):
    import re
    # TODO: make the if smarter
    if re.search(r"_%\d+d\.png$", image_path):
        out_mp4_path = get_manual_frame_to_vid_output_path(image_path)
        ffmpeg_stitch_video(ffmpeg_location=f_location, fps=fps, outmp4_path=out_mp4_path, stitch_from_frame=0, stitch_to_frame=-1, imgs_path=image_path, add_soundtrack=add_soundtrack, audio_path=audio_path, crf=f_crf, preset=f_preset)
    else:
        print("Please set correct image_path")
# end of 2 stitch frame to video funcs

# returns True if filename (could be also media URL) contains an audio stream, othehrwise False
def media_file_has_audio(filename, ffmpeg_location):
    result = subprocess.run([ffmpeg_location, "-i", filename, "-af", "volumedetect", "-f", "null", "-"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    output = result.stderr.decode()
    return True if "Stream #0:1: Audio: " in output or "Stream #0:1(und): Audio" in output else False

# download gifski binaries if needed - linux and windows only atm (apple users won't even see the option)
def check_and_download_gifski(models_folder, current_user_os):
    from basicsr.utils.download_util import load_file_from_url
    
    if current_user_os == 'Windows':
        file_name = 'gifski.exe'
        checksum_value = 'b0dd261ad021c31c7fdb99db761b45165e6b2a7e8e09c5d070a2b8064b575d7a4976c364d8508b28a6940343119b16a23e9f7d76f1f3d5ff02289d3068b469cf'
        download_url = 'https://github.com/hithereai/d/releases/download/giski-windows-bin/gifski.exe'
    elif current_user_os == 'Linux':
        file_name = 'gifski'
        checksum_value = 'e65bf9502bca520a7fd373397e41078d5c73db12ec3e9b47458c282d076c04fa697adecb5debb5d37fc9cbbee0673bb95e78d92c1cf813b4f5cc1cabe96880ff'
        download_url = 'https://github.com/hithereai/d/releases/download/gifski-linux-bin/gifski'
        
    file_path = os.path.join(models_folder, file_name)
    
    if not os.path.exists(file_path):
        load_file_from_url(download_url, models_folder)
        if current_user_os == 'Linux':
            os.chmod(file_path, 0o755)
        if checksum(file_path) != checksum_value:
            raise Exception(f"Error while downloading {file_name}. Please download from here: {download_url} and place in: {models_folder}")
           
# create a gif using gifski - limited to up to 30 fps (from the ui; if users wanna try to hack it, results are not good, but possible up to 100 fps theoretically)   
def make_gifski_gif(imgs_raw_path, imgs_batch_id, fps, models_folder, current_user_os):
    import glob
    print(f"\033[0;33mStitching *gif* from frames using Gifski:\033[0m")
    start_time = time.time()
    
    gifski_location = os.path.join(models_folder, 'gifski' + ('.exe' if current_user_os == 'Windows' else ''))
    final_gif_path = os.path.join(imgs_raw_path, imgs_batch_id + '.gif')
    if current_user_os == "Linux":
        input_img_pattern = imgs_batch_id + '_0*.png'
        input_img_files = [os.path.join(imgs_raw_path, file) for file in sorted(glob.glob(os.path.join(imgs_raw_path, input_img_pattern)))]
        cmd = [gifski_location, '-o', final_gif_path] + input_img_files + ['--fps', str(fps), '--quality', str(95)]
    elif current_user_os == "Windows":
        input_img_pattern_for_gifski = os.path.join(imgs_raw_path, imgs_batch_id + '_0*.png')
        cmd = [gifski_location, '-o', final_gif_path, input_img_pattern_for_gifski, '--fps', str(fps), '--quality', str(95)]
    else: # should never this else as we check before, but just in case
        raise Exception(f"No support for OS type: {current_user_os}")
        
    check_and_download_gifski(models_folder, current_user_os)

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(stderr)
            raise RuntimeError(stderr)
        print(f"GIF stitching done in {time.time() - start_time:.2f} seconds!")
    except Exception as e:
        print(f"GIF stitching *failed* with error:\n{e}")
        
def check_and_download_realesrgan_ncnn(models_folder, current_user_os):
    import zipfile
    from basicsr.utils.download_util import load_file_from_url
    
    if current_user_os == 'Windows':
        zip_file_name = 'realesrgan-ncnn-windows.zip'
        executble_name = 'realesrgan-ncnn-vulkan.exe'
        zip_checksum_value = '1d073f520a4a3f6438a500fea88407964da6d4a87489719bedfa7445b76c019fdd95a5c39576ca190d7ac22c906b33d5250a6f48cb7eda2b6af3e86ec5f09dfc'
        download_url = 'https://github.com/hithereai/Real-ESRGAN/releases/download/real-esrgan-ncnn-windows/realesrgan-ncnn-windows.zip'
    elif current_user_os == 'Linux':
        zip_file_name = 'realesrgan-ncnn-linux.zip'
        executble_name = 'realesrgan-ncnn-vulkan'
        zip_checksum_value = 'df44c4e9a1ff66331079795f018a67fbad8ce37c4472929a56b5a38440cf96982d6e164a086b438c3d26d269025290dd6498bd50846bda8691521ecf8f0fafdf'
        download_url = 'https://github.com/hithereai/Real-ESRGAN/releases/download/real-esrgan-ncnn-linux/realesrgan-ncnn-linux.zip'

    realesrgan_ncnn_folder = os.path.join(models_folder, 'realesrgan_ncnn')
    realesrgan_exec_path = os.path.join(realesrgan_ncnn_folder, executble_name)
    realesrgan_zip_path = os.path.join(realesrgan_ncnn_folder, zip_file_name)
    if not os.path.exists(realesrgan_exec_path): # todo: change logic to check folder content
        os.makedirs(realesrgan_ncnn_folder)
        load_file_from_url(download_url, realesrgan_ncnn_folder)

        with zipfile.ZipFile(realesrgan_zip_path, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(realesrgan_zip_path))
            
        os.remove(realesrgan_zip_path)
        if current_user_os == 'Linux':
            os.chmod(realesrgan_exec_path, 0o755)
       
def make_upscale_v2(upscale_factor, upscale_model, keep_imgs, imgs_raw_path, imgs_batch_id, deforum_models_path, current_user_os, ffmpeg_location, ffmpeg_crf, ffmpeg_preset, fps, stitch_from_frame, stitch_to_frame, audio_path, add_soundtrack):
    
    clean_num_r_up_factor = extract_number(upscale_factor)

    # set paths
    realesrgan_ncnn_location = os.path.join(deforum_models_path, 'realesrgan_ncnn', 'realesrgan-ncnn-vulkan' + ('.exe' if current_user_os == 'Windows' else ''))
    upscaled_folder_path = os.path.join(imgs_raw_path, f"{imgs_batch_id}_upscaled")
    temp_folder_to_keep_raw_ims = os.path.join(upscaled_folder_path, 'temp_raw_imgs_to_upscale')
    out_upscaled_mp4_path = os.path.join(imgs_raw_path, f"{imgs_batch_id}_Upscaled_{upscale_factor}.mp4")
    # download upscaling model if needed
    check_and_download_realesrgan_ncnn(deforum_models_path, current_user_os)
    # make a folder with only the imgs we need to duplicate so we can call the ncnn with the folder syntax (quicker!)
    duplicate_pngs_from_folder(from_folder=imgs_raw_path, to_folder=temp_folder_to_keep_raw_ims, img_batch_id=imgs_batch_id, orig_vid_name='Dummy')
    cmd = [realesrgan_ncnn_location, '-i', temp_folder_to_keep_raw_ims, '-o', upscaled_folder_path, '-s', str(clean_num_r_up_factor), '-n', upscale_model]
    msg_to_print = "Upscaling raw output PNGs using realesrgan"
    console.print(msg_to_print, style="blink", end="")
    start_time = time.time()
    # make call to ncnn upscaling executble
    process = subprocess.run(cmd, capture_output=True, check=True, text=True)
    print("\r" + " " * len(msg_to_print), end="", flush=True)
    print(f"\rUpscaling \033[0;32mdone\033[0m in {time.time() - start_time:.2f} seconds!", flush=True)
    # set custom path for ffmpeg func below
    upscaled_imgs_path_for_ffmpeg = os.path.join(upscaled_folder_path, f"{imgs_batch_id}_%05d.png")
    # stitch video from upscaled pngs 
    ffmpeg_stitch_video(ffmpeg_location=ffmpeg_location, fps=fps, outmp4_path=out_upscaled_mp4_path, stitch_from_frame=stitch_from_frame, stitch_to_frame=stitch_to_frame, imgs_path=upscaled_imgs_path_for_ffmpeg, add_soundtrack=add_soundtrack, audio_path=audio_path, crf=ffmpeg_crf, preset=ffmpeg_preset)

    # delete the duplicated raw imgs
    shutil.rmtree(temp_folder_to_keep_raw_ims)

    if not keep_imgs:
        shutil.rmtree(upscaled_folder_path)