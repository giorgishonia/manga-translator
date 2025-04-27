import os, json
import cv2, shutil
from datetime import datetime
from typing import List
from PySide6 import QtCore
from PySide6.QtGui import QColor

from modules.detection.processor import TextBlockDetector
from modules.ocr.processor import OCRProcessor
from modules.translation.processor import Translator
from modules.utils.textblock import TextBlock, sort_blk_list
from modules.utils.pipeline_utils import inpaint_map, get_config
from modules.rendering.render import get_best_render_area, pyside_word_wrap
from modules.utils.pipeline_utils import generate_mask, get_language_code, is_directory_empty
from modules.utils.translator_utils import get_raw_translation, get_raw_text, format_translations, set_upper_case
from modules.utils.archives import make

from app.ui.canvas.rectangle import MoveableRectItem
from app.ui.canvas.text_item import OutlineInfo, OutlineType
from app.ui.canvas.save_renderer import ImageSaveRenderer

class ComicTranslatePipeline:
    def __init__(self, main_page):
        self.main_page = main_page
        self.pipeline_running = False
        self.block_detector_cache = None
        self.inpainter_cache = None
        self.cached_inpainter_key = None
        self.ocr = OCRProcessor()

    def load_box_coords(self, blk_list: List[TextBlock]):
        self.main_page.image_viewer.clear_rectangles()
        if self.main_page.image_viewer.hasPhoto() and blk_list:
            for blk in blk_list:
                x1, y1, x2, y2 = blk.xyxy
                rect = QtCore.QRectF(0, 0, x2 - x1, y2 - y1)
                rect_item = MoveableRectItem(rect, self.main_page.image_viewer.photo)
                if blk.tr_origin_point:
                    rect_item.setTransformOriginPoint(QtCore.QPointF(*blk.tr_origin_point))
                rect_item.setPos(x1,y1)
                rect_item.setRotation(blk.angle)
                self.main_page.connect_rect_item_signals(rect_item)
                self.main_page.image_viewer.rectangles.append(rect_item)

            rect = self.main_page.find_corresponding_rect(self.main_page.blk_list[0], 0.5)
            self.main_page.image_viewer.select_rectangle(rect)
            self.main_page.set_tool('box')

    def detect_blocks(self, load_rects=True):
        if self.main_page.image_viewer.hasPhoto():
            if self.block_detector_cache is None:
                self.block_detector_cache = TextBlockDetector(self.main_page.settings_page)
            image = self.main_page.image_viewer.get_cv2_image()
            blk_list = self.block_detector_cache.detect(image)

            return blk_list, load_rects

    def on_blk_detect_complete(self, result): 
        blk_list, load_rects = result
        source_lang = self.main_page.s_combo.currentText()
        source_lang_english = self.main_page.lang_mapping.get(source_lang, source_lang)
        rtl = True if source_lang_english == 'Japanese' else False
        blk_list = sort_blk_list(blk_list, rtl)
        self.main_page.blk_list = blk_list
        if load_rects:
            self.load_box_coords(blk_list)


    def manual_inpaint(self):
        image_viewer = self.main_page.image_viewer
        settings_page = self.main_page.settings_page
        mask = image_viewer.get_mask_for_inpainting()
        image = image_viewer.get_cv2_image()

        if self.inpainter_cache is None or self.cached_inpainter_key != settings_page.get_tool_selection('inpainter'):
            device = 'cuda' if settings_page.is_gpu_enabled() else 'cpu'
            inpainter_key = settings_page.get_tool_selection('inpainter')
            InpainterClass = inpaint_map[inpainter_key]
            self.inpainter_cache = InpainterClass(device)
            self.cached_inpainter_key = inpainter_key

        config = get_config(settings_page)
        inpaint_input_img = self.inpainter_cache(image, mask, config)
        inpaint_input_img = cv2.convertScaleAbs(inpaint_input_img) 

        return inpaint_input_img
    
    def inpaint_complete(self, result):
        inpainted, original_image = result
        self.main_page.set_cv2_image(inpainted)
        # get_best_render_area(self.main_page.blk_list, original_image, inpainted)
    
    def inpaint(self):
        image = self.main_page.image_viewer.get_cv2_image()
        inpainted = self.manual_inpaint()
        return inpainted, image
    
    def get_selected_block(self):
        rect = self.main_page.image_viewer.selected_rect
        srect = rect.mapRectToScene(rect.rect())
        srect_coords = srect.getCoords()
        blk = self.main_page.find_corresponding_text_block(srect_coords)
        return blk

    def OCR_image(self, single_block=False):
        source_lang = self.main_page.s_combo.currentText()
        if self.main_page.image_viewer.hasPhoto() and self.main_page.image_viewer.rectangles:
            image = self.main_page.image_viewer.get_cv2_image()
            self.ocr.initialize(self.main_page, source_lang)
            if single_block:
                blk = self.get_selected_block()
                self.ocr.process(image, [blk])
            else:
                self.ocr.process(image, self.main_page.blk_list)
                print("Block Length: ", len(self.main_page.blk_list))

    def translate_image(self, single_block=False):
        source_lang = self.main_page.s_combo.currentText()
        target_lang = self.main_page.t_combo.currentText()
        if self.main_page.image_viewer.hasPhoto() and self.main_page.blk_list:
            settings_page = self.main_page.settings_page
            image = self.main_page.image_viewer.get_cv2_image()
            extra_context = settings_page.get_llm_settings()['extra_context']

            upper_case = settings_page.ui.uppercase_checkbox.isChecked()

            translator = Translator(self.main_page, source_lang, target_lang)
            if single_block:
                blk = self.get_selected_block()
                translator.translate([blk], image, extra_context)
                set_upper_case([blk], upper_case)
            else:
                translator.translate(self.main_page.blk_list, image, extra_context)
                set_upper_case(self.main_page.blk_list, upper_case)

    def skip_save(self, directory, timestamp, base_name, extension, archive_bname, image):
        path = os.path.join(directory, f"comic_translate_{timestamp}", "translated_images", archive_bname)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        cv2.imwrite(os.path.join(path, f"{base_name}_translated{extension}"), image)

    def log_skipped_image(self, directory, timestamp, image_path):
        log_file = os.path.join(directory, f"comic_translate_{timestamp}", "skipped_images.log")
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{image_path}\n")

    def batch_process(self):
        timestamp = datetime.now().strftime("%b-%d-%Y_%I-%M-%S%p")
        total_images = len(self.main_page.image_files)
        settings_page = self.main_page.settings_page # Get settings once
        export_settings = settings_page.get_export_settings() # Get export settings once
        extra_context = settings_page.get_llm_settings()['extra_context'] # Get context once

        # --- Batching Initialization ---
        batch_size = 10
        translation_batches = [] # Holds data for the current translation batch
        image_batches_data = {} # Holds all processed data for each image

        # --- Main Image Processing Loop (Collect data and process batches) ---
        for index, image_path in enumerate(self.main_page.image_files):

            self.main_page.progress_update.emit(index, total_images, 0, 10, True) # Step 0: Starting

            source_lang = self.main_page.image_states[image_path]['source_lang']
            target_lang = self.main_page.image_states[image_path]['target_lang']
            target_lang_en = self.main_page.lang_mapping.get(target_lang, None)
            trg_lng_cd = get_language_code(target_lang_en)

            base_name = os.path.splitext(os.path.basename(image_path))[0]
            extension = os.path.splitext(image_path)[1]
            directory = os.path.dirname(image_path)
            archive_bname = ""
            # Find archive info if necessary
            for archive in self.main_page.file_handler.archive_info:
                if image_path in archive.get('extracted_images', []):
                    directory = os.path.dirname(archive['archive_path'])
                    archive_bname = os.path.splitext(os.path.basename(archive['archive_path']))[0]
                    break

            image = cv2.imread(image_path)
            if image is None:
                print(f"Error: Could not read image {image_path}. Skipping.")
                self.log_skipped_image(directory, timestamp, image_path) # Log skip
                continue # Skip to next image

            # Step 1 & 2: Text Block Detection
            self.main_page.progress_update.emit(index, total_images, 1, 10, False)
            if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break
            if self.block_detector_cache is None: self.block_detector_cache = TextBlockDetector(settings_page)
            blk_list = self.block_detector_cache.detect(image)
            self.main_page.progress_update.emit(index, total_images, 2, 10, False)
            if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

            if not blk_list:
                self.skip_save(directory, timestamp, base_name, extension, archive_bname, image)
                self.main_page.image_skipped.emit(image_path, "Text Blocks", "")
                self.log_skipped_image(directory, timestamp, image_path)
                continue

            # Step 3: OCR
            self.ocr.initialize(self.main_page, source_lang)
            try:
                self.ocr.process(image, blk_list)
                source_lang_english = self.main_page.lang_mapping.get(source_lang, source_lang)
                rtl = True if source_lang_english == 'Japanese' else False
                blk_list = sort_blk_list(blk_list, rtl)
            except Exception as e:
                error_message = str(e); print(error_message)
                self.skip_save(directory, timestamp, base_name, extension, archive_bname, image)
                self.main_page.image_skipped.emit(image_path, "OCR", error_message)
                self.log_skipped_image(directory, timestamp, image_path)
                continue
            self.main_page.progress_update.emit(index, total_images, 3, 10, False)
            if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

            # Step 4 & 5: Inpainting (Clean Image)
            if self.inpainter_cache is None or self.cached_inpainter_key != settings_page.get_tool_selection('inpainter'):
                device = 'cuda' if settings_page.is_gpu_enabled() else 'cpu'
                inpainter_key = settings_page.get_tool_selection('inpainter')
                InpainterClass = inpaint_map[inpainter_key]
                self.inpainter_cache = InpainterClass(device)
                self.cached_inpainter_key = inpainter_key
            config = get_config(settings_page)
            mask = generate_mask(image, blk_list)
            self.main_page.progress_update.emit(index, total_images, 4, 10, False)
            if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break
            inpaint_input_img = self.inpainter_cache(image, mask, config)
            inpaint_input_img = cv2.convertScaleAbs(inpaint_input_img)
            self.main_page.image_history[image_path] = [image_path] # Store history for cleaned image
            self.main_page.current_history_index[image_path] = 0
            self.main_page.image_processed.emit(index, inpaint_input_img, image_path) # Show cleaned image
            inpaint_input_img_rgb = cv2.cvtColor(inpaint_input_img, cv2.COLOR_BGR2RGB) # Keep RGB version for rendering
            if export_settings['export_inpainted_image']:
                path = os.path.join(directory, f"comic_translate_{timestamp}", "cleaned_images", archive_bname)
                if not os.path.exists(path): os.makedirs(path, exist_ok=True)
                cv2.imwrite(os.path.join(path, f"{base_name}_cleaned{extension}"), inpaint_input_img) # Save BGR version
            self.main_page.progress_update.emit(index, total_images, 5, 10, False) # Step 5: Inpainting done
            if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

            # --- Store data for batch translation ---
            current_image_data = {
                'image_path': image_path, 'original_index': index, 'image': image, # Use original image for context if needed
                'blk_list': blk_list, 'source_lang': source_lang, 'target_lang': target_lang,
                'base_name': base_name, 'extension': extension, 'archive_bname': archive_bname,
                'timestamp': timestamp, 'directory': directory, 'trg_lng_cd': trg_lng_cd,
                'inpaint_input_img_rgb': inpaint_input_img_rgb, # Store RGB inpainted image for rendering
                'skipped': False, 'error_message': ""
            }
            image_batches_data[image_path] = current_image_data
            translation_batches.append(current_image_data)

            # --- Process translation batch ---
            if len(translation_batches) == batch_size or index == total_images - 1:
                combined_blk_list = []
                batch_indices_map = {}
                current_combined_index = 0
                translator = None # Initialize translator once per batch

                for data in translation_batches:
                    start_index = current_combined_index
                    img_blk_list = data['blk_list']
                    combined_blk_list.extend(img_blk_list)
                    end_index = current_combined_index + len(img_blk_list)
                    batch_indices_map[(start_index, end_index)] = data
                    current_combined_index = end_index
                    # Initialize translator based on the first image's languages in the batch
                    if translator is None:
                         translator = Translator(self.main_page, data['source_lang'], data['target_lang'])

                if combined_blk_list and translator:
                    self.main_page.progress_update.emit(index, total_images, 6, 10, False) # Step 6: Translation start (use last index of batch for progress)
                    if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break
                    try:
                        # Use representative image/context from the first item for LLMs if needed
                        representative_image = translation_batches[0]['image']
                        # Note: extra_context is fetched outside the loop
                        translated_combined_blk_list = translator.translate(
                            combined_blk_list, representative_image, extra_context
                        )
                        # Distribute results
                        for (start, end), original_data in batch_indices_map.items():
                            original_data['blk_list'] = translated_combined_blk_list[start:end]
                    except Exception as e:
                        error_message = str(e); print(f"Batch translation error: {error_message}")
                        for data in translation_batches:
                            data['skipped'] = True
                            data['error_message'] = error_message
                # Clear batch
                translation_batches = []

        # --- End of Main Image Processing Loop ---
        if self.main_page.current_worker and self.main_page.current_worker.is_cancelled:
             print("Batch processing cancelled.")
             self.main_page.current_worker = None
             # Consider how to handle partially processed batches if needed
        else:
            # --- Post-Translation Processing Loop ---
            for image_path, processed_data in image_batches_data.items():
                index = processed_data['original_index'] # Use original index for progress

                # Check if skipped during translation batch
                if processed_data['skipped']:
                    self.skip_save(processed_data['directory'], processed_data['timestamp'], processed_data['base_name'], processed_data['extension'], processed_data['archive_bname'], processed_data['image'])
                    self.main_page.image_skipped.emit(image_path, "Translator", processed_data['error_message'])
                    self.log_skipped_image(processed_data['directory'], processed_data['timestamp'], image_path)
                    continue # Skip post-processing for this image

                # Retrieve processed data
                blk_list = processed_data['blk_list']
                image = processed_data['image'] # Original image
                inpaint_input_img_rgb = processed_data['inpaint_input_img_rgb'] # RGB Inpainted image
                base_name = processed_data['base_name']
                extension = processed_data['extension']
                archive_bname = processed_data['archive_bname']
                timestamp = processed_data['timestamp']
                directory = processed_data['directory']
                trg_lng_cd = processed_data['trg_lng_cd']

                # Step 7: Export Texts / Validate
                entire_raw_text = get_raw_text(blk_list)
                entire_translated_text = get_raw_translation(blk_list)
                try:
                    raw_text_obj = json.loads(entire_raw_text) if entire_raw_text.strip() else {}
                    translated_text_obj = json.loads(entire_translated_text) if entire_translated_text.strip() else {}
                    if not blk_list or (not raw_text_obj and not translated_text_obj and any(blk.text for blk in blk_list)): # Check if blocks exist but text is empty
                         # If blocks exist but text is empty/invalid JSON, potentially skip or log warning
                         print(f"Warning: Empty or invalid text JSON for {image_path}")
                         # Decide if skipping is appropriate here. For now, continue processing.
                         # self.skip_save(...) etc. if needed
                except json.JSONDecodeError as e:
                    error_message = f"JSON Decode Error: {str(e)}" ; print(error_message)
                    self.skip_save(directory, timestamp, base_name, extension, archive_bname, image)
                    self.main_page.image_skipped.emit(image_path, "Translator", error_message) # Report as Translator issue
                    self.log_skipped_image(directory, timestamp, image_path)
                    continue

                if export_settings['export_raw_text']:
                    path = os.path.join(directory, f"comic_translate_{timestamp}", "raw_texts", archive_bname)
                    if not os.path.exists(path): os.makedirs(path, exist_ok=True)
                    file_path = os.path.join(path, f"{base_name}_raw.txt")
                    with open(file_path, 'w', encoding='UTF-8') as file: file.write(entire_raw_text)

                if export_settings['export_translated_text']:
                    path = os.path.join(directory, f"comic_translate_{timestamp}", "translated_texts", archive_bname)
                    if not os.path.exists(path): os.makedirs(path, exist_ok=True)
                    file_path = os.path.join(path, f"{base_name}_translated.txt")
                    with open(file_path, 'w', encoding='UTF-8') as file: file.write(entire_translated_text)

                self.main_page.progress_update.emit(index, total_images, 7, 10, False) # Step 7: Text Export Done
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

                # Step 8 & 9: Text Rendering
                render_settings = self.main_page.render_settings()
                upper_case = render_settings.upper_case
                outline = render_settings.outline
                if trg_lng_cd is not None: format_translations(blk_list, trg_lng_cd, upper_case=upper_case)
                else: format_translations(blk_list, '', upper_case=upper_case) # Fallback
                get_best_render_area(blk_list, image, inpaint_input_img_rgb) # Use RGB inpainted image

                font = render_settings.font_family
                font_color = QColor(render_settings.color)
                max_font_size = render_settings.max_font_size
                min_font_size = render_settings.min_font_size
                line_spacing = float(render_settings.line_spacing)
                outline_width = float(render_settings.outline_width)
                outline_color = QColor(render_settings.outline_color)
                bold = render_settings.bold; italic = render_settings.italic; underline = render_settings.underline
                alignment_id = render_settings.alignment_id
                alignment = self.main_page.button_to_alignment[alignment_id]
                direction = render_settings.direction

                text_items_state = []
                for blk in blk_list:
                    if not blk.translation or not blk.translation.strip(): continue # Skip empty translations
                    x1, y1, width, height = blk.xywh
                    translation, font_size = pyside_word_wrap(blk.translation, font, width, height,
                                                            line_spacing, outline_width, bold, italic, underline,
                                                            alignment, direction, max_font_size, min_font_size)
                    if index == self.main_page.curr_img_idx: self.main_page.blk_rendered.emit(translation, font_size, blk) # Update UI if current
                    if trg_lng_cd is not None and any(lang in trg_lng_cd.lower() for lang in ['zh', 'ja', 'th']): translation = translation.replace(' ', '')

                    text_items_state.append({
                        'text': translation, 'font_family': font, 'font_size': font_size, 'text_color': font_color,
                        'alignment': alignment, 'line_spacing': line_spacing, 'outline_color': outline_color,
                        'outline_width': outline_width, 'bold': bold, 'italic': italic, 'underline': underline,
                        'position': (x1, y1), 'rotation': blk.angle, 'scale': 1.0,
                        'transform_origin': blk.tr_origin_point, 'width': width, 'direction': direction,
                        'selection_outlines': [OutlineInfo(0, len(translation), outline_color, outline_width, OutlineType.Full_Document)] if outline else []
                    })

                self.main_page.image_states[image_path]['viewer_state'].update({'text_items_state': text_items_state})
                self.main_page.progress_update.emit(index, total_images, 8, 10, False) # Step 8: State Updated
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

                # Step 10: Saving final rendered image
                self.main_page.image_states[image_path].update({'blk_list': blk_list})
                if index == self.main_page.curr_img_idx: self.main_page.blk_list = blk_list # Update current block list

                render_save_dir = os.path.join(directory, f"comic_translate_{timestamp}", "translated_images", archive_bname)
                if not os.path.exists(render_save_dir): os.makedirs(render_save_dir, exist_ok=True)
                sv_pth = os.path.join(render_save_dir, f"{base_name}_translated{extension}")

                # Render using the RGB inpainted image
                im_to_render = cv2.cvtColor(inpaint_input_img_rgb, cv2.COLOR_RGB2BGR) # Convert back to BGR for saving
                renderer = ImageSaveRenderer(im_to_render)
                viewer_state = self.main_page.image_states[image_path]['viewer_state']
                renderer.add_state_to_image(viewer_state)
                renderer.save_image(sv_pth)

                self.main_page.progress_update.emit(index, total_images, 9, 10, False) # Step 9: Final Image Saved (adjust step counts if needed)
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled: break

        # --- End of Post-Processing Loop ---
        if self.main_page.current_worker and self.main_page.current_worker.is_cancelled:
             print("Batch processing cancelled during post-processing.")
             self.main_page.current_worker = None

        # --- Archiving Logic (Seems independent of the main image loop) ---
        archive_info_list = self.main_page.file_handler.archive_info
        if archive_info_list:
            save_as_settings = settings_page.get_export_settings()['save_as']
            for archive_index, archive in enumerate(archive_info_list):
                archive_index_input = total_images + archive_index

                self.main_page.progress_update.emit(archive_index_input, total_images, 1, 3, True)
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled:
                    self.main_page.current_worker = None
                    break

                archive_path = archive['archive_path']
                archive_ext = os.path.splitext(archive_path)[1]
                archive_bname = os.path.splitext(os.path.basename(archive_path))[0]
                archive_directory = os.path.dirname(archive_path)
                save_as_ext = f".{save_as_settings[archive_ext.lower()]}"

                save_dir = os.path.join(archive_directory, f"comic_translate_{timestamp}", "translated_images", archive_bname)
                check_from = os.path.join(archive_directory, f"comic_translate_{timestamp}")

                self.main_page.progress_update.emit(archive_index_input, total_images, 2, 3, True)
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled:
                    self.main_page.current_worker = None
                    break

                # Create the new archive
                output_base_name = f"{archive_bname}"
                make(save_as_ext=save_as_ext, input_dir=save_dir, 
                    output_dir=archive_directory, output_base_name=output_base_name)

                self.main_page.progress_update.emit(archive_index_input, total_images, 3, 3, True)
                if self.main_page.current_worker and self.main_page.current_worker.is_cancelled:
                    self.main_page.current_worker = None
                    break

                # Clean up temporary 
                if os.path.exists(save_dir):
                    shutil.rmtree(save_dir)
                # The temp dir is removed when closing the app

                if is_directory_empty(check_from):
                    shutil.rmtree(check_from)






