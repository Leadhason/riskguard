import json
import logging
import time
from typing import Dict, Any, Optional, Tuple
from io import BytesIO

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

class AWSTextractService:
    """Local Tesseract OCR and Backblaze B2 service for Ghana Card ID document processing"""
    
    def __init__(self):
        """Initialize Backblaze B2 client if configured"""
        try:
            # Initialize Backblaze B2 client (S3-compatible API)
            b2_access_key = getattr(settings, 'B2_APPLICATION_KEY_ID', None)
            b2_secret_key = getattr(settings, 'B2_APPLICATION_KEY', None)
            b2_endpoint_url = getattr(settings, 'B2_ENDPOINT_URL', None)
            b2_region = getattr(settings, 'B2_REGION', 'us-east-1')
            
            self.s3_bucket = getattr(settings, 'B2_BUCKET_NAME', None)
            self.b2_configured = bool(b2_access_key and b2_secret_key and b2_endpoint_url and self.s3_bucket)
            
            if self.b2_configured:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=b2_access_key,
                    aws_secret_access_key=b2_secret_key,
                    endpoint_url=b2_endpoint_url,
                    region_name=b2_region
                )
                logger.info("Backblaze B2 client initialized successfully")
            else:
                self.s3_client = None
                logger.warning("Backblaze B2 is not fully configured, local processing will run without B2 uploads")
                
        except Exception as e:
            logger.error(f"Failed to initialize Backblaze B2 client: {str(e)}")
            self.s3_client = None
            self.b2_configured = False
    
    def validate_aws_credentials(self) -> bool:
        """Validate B2 credentials if configured, otherwise return True for local-only mode"""
        if not self.b2_configured or not self.s3_client:
            logger.info("Backblaze B2 is not configured - using local Tesseract OCR mode")
            return True
            
        try:
            # Test B2 access
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            logger.info("[OK] Backblaze B2 bucket connection verified")
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                logger.error(f"B2 bucket {self.s3_bucket} does not exist")
            elif error_code in ['AccessDenied', 'Forbidden']:
                logger.error("B2 credentials do not have required permissions")
            return False
        except Exception as e:
            logger.error(f"B2 validation failed: {str(e)}")
            return False
    
    def upload_to_s3(self, image_file, file_key: str) -> str:
        """Upload image file to Backblaze B2 and return the key (noop if B2 not configured)"""
        if not self.b2_configured or not self.s3_client:
            return file_key
            
        try:
            # Reset file pointer
            if hasattr(image_file, 'seek'):
                image_file.seek(0)
            
            # Validate and optimize image
            optimized_image = self._optimize_image_for_textract(image_file)
            
            # Upload to R2
            self.s3_client.upload_fileobj(
                optimized_image,
                self.s3_bucket,
                file_key,
                ExtraArgs={
                    'ContentType': 'image/jpeg'
                }
            )
            
            logger.info(f"Successfully uploaded image to Cloudflare R2: {file_key}")
            return file_key
            
        except Exception as e:
            logger.error(f"Failed to upload image to Cloudflare R2: {str(e)}")
            # We don't fail document processing if audit logging fails
            return file_key
    
    def _optimize_image_for_textract(self, image_file) -> BytesIO:
        """Optimize image size and properties for processing"""
        try:
            # Reset file pointer
            if hasattr(image_file, 'seek'):
                image_file.seek(0)
            
            # Open image with PIL
            image = Image.open(image_file)
            
            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Get image dimensions
            width, height = image.size
            
            # Target requirements: max 10MB, max 4096x4096 pixels
            max_dimension = 4096
            max_file_size = 10 * 1024 * 1024  # 10MB
            
            # Resize if too large
            if width > max_dimension or height > max_dimension:
                ratio = min(max_dimension / width, max_dimension / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.info(f"Resized image from {width}x{height} to {new_width}x{new_height}")
            
            # Save optimized image to BytesIO
            optimized_buffer = BytesIO()
            
            for quality in [95, 85, 75, 65]:
                optimized_buffer.seek(0)
                optimized_buffer.truncate()
                
                image.save(optimized_buffer, format='JPEG', quality=quality, optimize=True)
                
                if optimized_buffer.tell() <= max_file_size:
                    break
                    
                if quality == 65:
                    logger.warning(f"Image still too large after optimization: {optimized_buffer.tell()} bytes")
            
            optimized_buffer.seek(0)
            return optimized_buffer
            
        except Exception as e:
            logger.error(f"Failed to optimize image: {str(e)}")
            raise
    
    def analyze_ghana_card(self, front_image_file, back_image_file, user_id: str) -> Dict[str, Any]:
        """
        Analyze Ghana Card images using local Tesseract OCR with optional Backblaze B2 backup
        
        Args:
            front_image_file: Front image of Ghana Card
            back_image_file: Back image of Ghana Card
            user_id: User identifier for file naming
            
        Returns:
            Dict containing extracted information matching the AWS Textract format
        """
        start_time = time.time()
        
        try:
            # Validate credentials if configured
            if not self.validate_aws_credentials():
                raise Exception("Backblaze B2 credentials validation failed")
            
            # Generate unique file keys for optional upload
            timestamp = str(int(time.time()))
            front_key = f"ghana-cards/{user_id}/front_{timestamp}.jpg"
            back_key = f"ghana-cards/{user_id}/back_{timestamp}.jpg"
            
            # Upload images to Backblaze B2 for auditing (optional/noop if not configured)
            if self.b2_configured:
                logger.info("Uploading images to Backblaze B2 for auditing...")
                front_s3_key = self.upload_to_s3(front_image_file, front_key)
                back_s3_key = self.upload_to_s3(back_image_file, back_key)
            else:
                front_s3_key = front_key
                back_s3_key = back_key
            
            # Ensure streams are reset before OCR
            if hasattr(front_image_file, 'seek'):
                front_image_file.seek(0)
            if hasattr(back_image_file, 'seek'):
                back_image_file.seek(0)
            
            # Analyze front image locally (contains name and photo)
            logger.info("Analyzing front image with Tesseract OCR...")
            front_analysis = self._analyze_single_image(front_image_file, document_type="IDENTITY_DOCUMENT")
            
            # Ensure back stream is reset
            if hasattr(back_image_file, 'seek'):
                back_image_file.seek(0)
            
            # Analyze back image locally (contains ID number)
            logger.info("Analyzing back image with Tesseract OCR...")
            back_analysis = self._analyze_single_image(back_image_file, document_type="IDENTITY_DOCUMENT")
            
            # Extract structured information
            extracted_info = self._extract_ghana_card_info(front_analysis, back_analysis)
            
            # Clean up files in B2 if audit uploads were completed
            if self.b2_configured:
                self._cleanup_s3_files([front_s3_key, back_s3_key])
            
            processing_time = (time.time() - start_time) * 1000
            
            result = {
                'success': True,
                'processing_time_ms': round(processing_time, 2),
                'extracted_data': extracted_info,
                'textract_analysis': {
                    'front_confidence': self._get_average_confidence(front_analysis),
                    'back_confidence': self._get_average_confidence(back_analysis)
                }
            }
            
            logger.info(f"Ghana Card analysis completed successfully in {processing_time:.2f}ms")
            return result
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(f"Ghana Card analysis failed after {processing_time:.2f}ms: {str(e)}")
            
            return {
                'success': False,
                'error': str(e),
                'processing_time_ms': round(processing_time, 2),
                'extracted_data': {
                    'surname': None,
                    'firstname': None,
                    'ghana_card_number': None
                }
            }
    
    def _analyze_single_image(self, image_file, document_type: str = "IDENTITY_DOCUMENT") -> Dict[str, Any]:
        """Analyze a single image locally using Tesseract OCR and format to mimic AWS Textract AnalyzeID response"""
        try:
            import pytesseract
            
            if hasattr(image_file, 'seek'):
                image_file.seek(0)
                
            image = Image.open(image_file)
            
            # Perform local Tesseract OCR
            ocr_text = pytesseract.image_to_string(image)
            lines = ocr_text.split('\n')
            
            # Format to mimic Textract's LINE Blocks structure
            blocks = []
            for idx, line in enumerate(lines):
                line_stripped = line.strip()
                if line_stripped:
                    blocks.append({
                        'Id': f"block-{idx}",
                        'BlockType': 'LINE',
                        'Text': line_stripped,
                        'Confidence': 95.0
                    })
            
            # Positional & Keyword Field Extraction (Surname, Forenames, Personal ID number)
            fields = []
            normalized_lines = [l.strip() for l in lines if l.strip()]
            
            surname_val = None
            firstname_val = None
            id_val = None
            
            for i, line in enumerate(normalized_lines):
                line_upper = line.upper()
                
                # Extract Surname
                if any(kw in line_upper for kw in ['SURNAME', 'LAST NAME', 'SUR NAME', 'FAMILY NAME']):
                    # Same-line extraction
                    words = line.split()
                    kw_idx = -1
                    for idx, w in enumerate(words):
                        if any(kw in w.upper() for kw in ['SURNAME', 'LAST', 'SUR', 'FAMILY']):
                            kw_idx = idx
                            break
                    if kw_idx != -1 and len(words) > kw_idx + 1:
                        val = ' '.join(words[kw_idx+1:]).replace(':', '').strip()
                        if val.isalpha() and len(val) > 1:
                            surname_val = val
                    
                    # Next-line extraction
                    if not surname_val and i + 1 < len(normalized_lines):
                        next_line = normalized_lines[i+1]
                        if next_line.replace(' ', '').isalpha() and not any(k in next_line.upper() for k in ['FIRST', 'FORENAME', 'GIVEN', 'NAME', 'DATE', 'SEX', 'ID', 'NO']):
                            surname_val = next_line.strip()
                            
                # Extract First name/Forenames
                elif any(kw in line_upper for kw in ['FIRST NAME', 'GIVEN NAME', 'FORENAMES', 'FORENAME', 'FIRSTNAME']):
                    # Same-line extraction
                    words = line.split()
                    kw_idx = -1
                    for idx, w in enumerate(words):
                        if any(kw in w.upper() for kw in ['FIRST', 'GIVEN', 'FORENAMES', 'FORENAME', 'FIRSTNAME']):
                            kw_idx = idx
                            break
                    if kw_idx != -1 and len(words) > kw_idx + 1:
                        val = ' '.join(words[kw_idx+1:]).replace(':', '').strip()
                        if val.replace(' ', '').isalpha() and len(val) > 1:
                            firstname_val = val
                    
                    # Next-line extraction
                    if not firstname_val and i + 1 < len(normalized_lines):
                        next_line = normalized_lines[i+1]
                        if next_line.replace(' ', '').isalpha() and not any(k in next_line.upper() for k in ['SURNAME', 'LAST', 'SEX', 'DATE', 'ID', 'NO']):
                            firstname_val = next_line.strip()
                            
                # Extract ID Number
                elif any(kw in line_upper for kw in ['PERSONAL ID', 'CARD NO', 'ID NUMBER', 'CARD NUMBER', 'DOCUMENT NO', 'NO.']):
                    import re
                    # Look for GHA pattern
                    match = re.search(r'GHA[-\s]*[A-Z0-9]{9}[-\s]*\d', line_upper)
                    if match:
                        id_val = match.group(0)
                    else:
                        if i + 1 < len(normalized_lines):
                            next_line = normalized_lines[i+1].upper()
                            match_next = re.search(r'GHA[-\s]*[A-Z0-9]{9}[-\s]*\d', next_line)
                            if match_next:
                                id_val = match_next.group(0)
            
            # Map values to structured field types for the document analyzer
            if surname_val:
                fields.append({
                    'Type': {'Text': 'LAST_NAME'},
                    'ValueDetection': {'Text': surname_val, 'Confidence': 95.0}
                })
            if firstname_val:
                fields.append({
                    'Type': {'Text': 'FIRST_NAME'},
                    'ValueDetection': {'Text': firstname_val, 'Confidence': 95.0}
                })
            if id_val:
                fields.append({
                    'Type': {'Text': 'PERSONAL_ID_NUMBER'},
                    'ValueDetection': {'Text': id_val, 'Confidence': 95.0}
                })
                
            response = {
                'IdentityDocuments': [
                    {
                        'IdentityDocumentFields': fields,
                        'Blocks': blocks
                    }
                ],
                'Blocks': blocks
            }
            
            logger.info(f"Local Tesseract OCR completed. Extracted fields: {[f['Type']['Text'] for f in fields]}")
            return response
            
        except Exception as e:
            logger.error(f"Local Tesseract OCR analysis failed: {str(e)}")
            raise
    
    def _extract_ghana_card_info(self, front_analysis: Dict[str, Any], back_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured information from Textract analysis results with enhanced name parsing"""
        
        extracted_info = {
            'surname': None,
            'firstname': None,
            'ghana_card_number': None,
            'confidence_scores': {
                'surname': 0.0,
                'firstname': 0.0,
                'ghana_card_number': 0.0
            }
        }
        
        try:
            # Extract from front image (name information)
            front_fields = self._extract_identity_fields(front_analysis)
            
            # Extract from back image (ID number)
            back_fields = self._extract_identity_fields(back_analysis)
            
            # Combine all fields
            all_fields = {**front_fields, **back_fields}
            
            # Enhanced field mapping for Ghana Card with priority order
            ghana_number_fields = [
                'PERSONAL_ID_NUMBER',  # Highest priority - this is the actual Ghana card number
                'NATIONAL_ID',
                'ID_NUMBER', 
                'CARD_NUMBER',
                'DOCUMENT_NUMBER'  # Lowest priority - might be a different document reference
            ]
            
            field_mapping = {
                'FIRST_NAME': 'firstname',
                'LAST_NAME': 'surname', 
                'MIDDLE_NAME': 'firstname',  # Append to firstname
            }
            
            # Store all name parts for intelligent parsing
            name_parts = {
                'first_names': [],
                'last_names': [],
                'confidences': []
            }
            
            # Process name fields
            for textract_field, our_field in field_mapping.items():
                if textract_field in all_fields:
                    field_data = all_fields[textract_field]
                    value = field_data['value']
                    confidence = field_data['confidence']
                    
                    if textract_field in ['FIRST_NAME', 'MIDDLE_NAME']:
                        name_parts['first_names'].append(value)
                        name_parts['confidences'].append(confidence)
                    elif textract_field == 'LAST_NAME':
                        name_parts['last_names'].append(value)
                        name_parts['confidences'].append(confidence)
            
            # Process Ghana card number with priority
            logger.info("Searching for Ghana card number in structured fields...")
            for field_name in ghana_number_fields:
                if field_name in all_fields:
                    field_data = all_fields[field_name]
                    value = field_data['value']
                    confidence = field_data['confidence']
                    
                    logger.info(f"Found {field_name}: '{value}' (confidence: {confidence:.2f})")
                    
                    # Use the first (highest priority) field found
                    if not extracted_info['ghana_card_number']:
                        extracted_info['ghana_card_number'] = value
                        extracted_info['confidence_scores']['ghana_card_number'] = confidence
                        logger.info(f"Using {field_name} as Ghana card number: '{value}'")
                        break
            
            # Intelligent name parsing for complex names (only if structured fields found names)
            if name_parts['first_names'] or name_parts['last_names']:
                logger.info(f"Name parts found - First names: {name_parts['first_names']}, Last names: {name_parts['last_names']}")
                parsed_names = self._parse_complex_names(name_parts, front_analysis)
                logger.info(f"Parsed names result - First: '{parsed_names.get('firstname')}', Last: '{parsed_names.get('surname')}'")
                # Update names safely without overwriting other fields
                if parsed_names.get('firstname'):
                    extracted_info['firstname'] = parsed_names['firstname']
                    extracted_info['confidence_scores']['firstname'] = parsed_names['confidence_scores']['firstname']
                if parsed_names.get('surname'):
                    extracted_info['surname'] = parsed_names['surname'] 
                    extracted_info['confidence_scores']['surname'] = parsed_names['confidence_scores']['surname']
                
                # Additional check: Try to find missing middle names in raw text
                if len(name_parts['first_names']) == 1 and not name_parts.get('middle_names'):
                    logger.info("Only one first name found in structured fields, checking raw text for additional names...")
                    logger.info(f"Searching for names beyond: '{extracted_info['firstname']}' and '{extracted_info['surname']}'")
                    additional_names = self._find_additional_names_in_text(front_analysis, extracted_info['firstname'], extracted_info['surname'])
                    if additional_names:
                        logger.info(f"Found additional names in raw text: '{additional_names}'")
                        extracted_info['firstname'] = f"{extracted_info['firstname']} {additional_names}"
                    else:
                        logger.info("No additional names found in raw text")
            else:
                # Fallback: try original simple field mapping if no structured names found
                logger.info("No structured name fields found, trying simple field extraction...")
                for textract_field, our_field in field_mapping.items():
                    if textract_field in all_fields and our_field in ['firstname', 'surname']:
                        field_data = all_fields[textract_field]
                        value = field_data['value']
                        confidence = field_data['confidence']
                        
                        if our_field in extracted_info and not extracted_info[our_field]:  # Only set if field exists and is empty
                            extracted_info[our_field] = value
                            extracted_info['confidence_scores'][our_field] = confidence
            
            # Ghana card number extraction with fallback strategies
            if not extracted_info['ghana_card_number']:
                logger.info("Ghana card number not found in structured fields, trying original pattern matching...")
                # Try original method first (known to work for your card)
                extracted_info['ghana_card_number'], extracted_info['confidence_scores']['ghana_card_number'] = \
                    self._extract_ghana_number_from_text(back_analysis)
                
                # If original method fails, try enhanced method
                if not extracted_info['ghana_card_number']:
                    logger.info("Original method failed, trying enhanced pattern matching with OCR correction...")
                    try:
                        enhanced_number, enhanced_confidence = self._extract_ghana_number_enhanced(back_analysis, front_analysis)
                        extracted_info['ghana_card_number'] = enhanced_number
                        extracted_info['confidence_scores']['ghana_card_number'] = enhanced_confidence
                    except Exception as e:
                        logger.error(f"Enhanced Ghana card extraction failed: {str(e)}")
                        extracted_info['ghana_card_number'] = None
                        extracted_info['confidence_scores']['ghana_card_number'] = 0.0
            
            # Post-process Ghana Card number format and apply OCR correction
            if extracted_info['ghana_card_number']:
                # Apply OCR correction even to structured field results
                corrected_number = self._correct_ocr_errors(extracted_info['ghana_card_number'])
                if corrected_number != extracted_info['ghana_card_number']:
                    logger.info(f"Applied OCR correction to structured field: '{extracted_info['ghana_card_number']}' → '{corrected_number}'")
                    extracted_info['ghana_card_number'] = corrected_number
                
                # Format the number
                extracted_info['ghana_card_number'] = self._format_ghana_card_number(
                    extracted_info['ghana_card_number']
                )
            
            # Clean up names
            if extracted_info['surname']:
                extracted_info['surname'] = extracted_info['surname'].title().strip()
            if extracted_info['firstname']:
                extracted_info['firstname'] = extracted_info['firstname'].title().strip()
            
            # Log extraction results for debugging (with safe key access)
            logger.info(f"Final extraction results:")
            logger.info(f"  First name: '{extracted_info.get('firstname', 'None')}' (confidence: {extracted_info.get('confidence_scores', {}).get('firstname', 0.0):.2f})")
            logger.info(f"  Surname: '{extracted_info.get('surname', 'None')}' (confidence: {extracted_info.get('confidence_scores', {}).get('surname', 0.0):.2f})")
            logger.info(f"  Ghana card number: '{extracted_info.get('ghana_card_number', 'None')}' (confidence: {extracted_info.get('confidence_scores', {}).get('ghana_card_number', 0.0):.2f})")
            
            # Additional debug info
            logger.info(f"Structured fields found: {list(all_fields.keys())}")
            for field_name, field_data in all_fields.items():
                if 'NAME' in field_name:
                    logger.info(f"  {field_name}: '{field_data['value']}' (confidence: {field_data['confidence']:.2f})")
            logger.info(f"Extracted info keys: {list(extracted_info.keys())}")
            if not extracted_info.get('ghana_card_number'):
                logger.warning("🚨 Ghana card number extraction failed - check image quality or card format")
            
            return extracted_info
            
        except Exception as e:
            logger.error(f"Error extracting Ghana Card info: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return extracted_info
    
    def _parse_complex_names(self, name_parts: Dict[str, Any], front_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Intelligently parse complex names with multiple parts, hyphens, and middle names"""
        try:
            result = {
                'firstname': None,
                'surname': None,
                'confidence_scores': {
                    'firstname': 0.0,
                    'surname': 0.0
                }
            }
            
            # Combine all first names
            if name_parts['first_names']:
                result['firstname'] = ' '.join(name_parts['first_names']).strip()
                result['confidence_scores']['firstname'] = sum(name_parts['confidences']) / len(name_parts['confidences'])
            
            # Handle surnames
            if name_parts['last_names']:
                # Take the surname with highest confidence
                best_surname = max(zip(name_parts['last_names'], name_parts['confidences']), key=lambda x: x[1])
                result['surname'] = best_surname[0].strip()
                result['confidence_scores']['surname'] = best_surname[1]
            
            # Fallback: Try to extract names from raw text if structured fields failed
            if not result['firstname'] or not result['surname']:
                logger.info("Attempting fallback name extraction from raw text...")
                fallback_names = self._extract_names_from_text(front_analysis)
                if fallback_names['firstname'] and not result['firstname']:
                    result['firstname'] = fallback_names['firstname']
                    result['confidence_scores']['firstname'] = fallback_names['firstname_confidence']
                if fallback_names['surname'] and not result['surname']:
                    result['surname'] = fallback_names['surname']
                    result['confidence_scores']['surname'] = fallback_names['surname_confidence']
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing complex names: {str(e)}")
            return {
                'firstname': None,
                'surname': None,
                'confidence_scores': {'firstname': 0.0, 'surname': 0.0}
            }
    
    def _extract_names_from_text(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract names from raw text as fallback method"""
        try:
            result = {
                'firstname': None,
                'surname': None,
                'firstname_confidence': 0.0,
                'surname_confidence': 0.0
            }
            
            # Get all text blocks from the analysis
            text_blocks = []
            if 'Blocks' in analysis_result:
                for block in analysis_result['Blocks']:
                    if block.get('BlockType') == 'LINE' and 'Text' in block:
                        text = block['Text'].strip()
                        confidence = block.get('Confidence', 0.0)
                        if text and confidence > 50:  # Only consider high-confidence text
                            text_blocks.append((text, confidence))
            
            # Look for name patterns (common Ghana name structures)
            for text, confidence in text_blocks:
                words = text.split()
                if len(words) >= 2:
                    # Look for patterns like "SURNAME: John Doe" or "NAME: John Doe"
                    if any(keyword in text.upper() for keyword in ['SURNAME', 'LAST NAME', 'FAMILY NAME']):
                        potential_surname = ' '.join(words[1:])  # Take everything after the keyword
                        if len(potential_surname.split()) == 1:  # Single word surnames are more reliable
                            result['surname'] = potential_surname.title()
                            result['surname_confidence'] = confidence
                    
                    elif any(keyword in text.upper() for keyword in ['FIRST NAME', 'GIVEN NAME', 'FORENAME']):
                        potential_firstname = ' '.join(words[1:])  # Take everything after the keyword
                        result['firstname'] = potential_firstname.title()
                        result['firstname_confidence'] = confidence
                    
                    # Look for full name patterns with multiple words (likely first names)
                    elif len(words) >= 3 and all(word.isalpha() for word in words):
                        # Assume last word is surname, rest are first names
                        potential_firstname = ' '.join(words[:-1])
                        potential_surname = words[-1]
                        
                        if not result['firstname'] and confidence > result['firstname_confidence']:
                            result['firstname'] = potential_firstname.title()
                            result['firstname_confidence'] = confidence
                        if not result['surname'] and confidence > result['surname_confidence']:
                            result['surname'] = potential_surname.title()
                            result['surname_confidence'] = confidence
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting names from text: {str(e)}")
            return {
                'firstname': None,
                'surname': None, 
                'firstname_confidence': 0.0,
                'surname_confidence': 0.0
            }
    
    def _extract_ghana_number_enhanced(self, back_analysis: Dict[str, Any], front_analysis: Dict[str, Any]) -> tuple:
        """Enhanced Ghana card number extraction with multiple strategies and OCR correction"""
        try:
            candidates = []
            
            # Strategy 1: Pattern matching with multiple formats
            ghana_patterns = [
                r'GHA[- ]?(\d{9})[- ]?(\d)',  # Standard format
                r'GHA[- ]?([A-Z0-9]{9})[- ]?(\d)',  # Allow mixed alphanumeric
                r'(\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d)',  # Numbers only
                r'([A-Z]{3}[- ]?\d{9}[- ]?\d)',  # Full format
            ]
            
            # Check both back and front images
            for analysis, source in [(back_analysis, 'back'), (front_analysis, 'front')]:
                if 'Blocks' in analysis:
                    for block in analysis['Blocks']:
                        if block.get('BlockType') == 'LINE' and 'Text' in block:
                            text = block['Text'].strip().upper()
                            confidence = block.get('Confidence', 0.0)
                            
                            for pattern in ghana_patterns:
                                match = re.search(pattern, text)
                                if match:
                                    if len(match.groups()) == 2:
                                        ghana_number = f"GHA-{match.group(1)}-{match.group(2)}"
                                    else:
                                        ghana_number = self._standardize_ghana_number(match.group(0))
                                    
                                    # Apply OCR error correction
                                    corrected_number = self._correct_ocr_errors(ghana_number)
                                    
                                    candidates.append({
                                        'number': corrected_number,
                                        'confidence': confidence,
                                        'source': source,
                                        'original_text': text
                                    })
                                    
                                    logger.info(f"Found Ghana number candidate from {source}: '{corrected_number}' (original: '{ghana_number}', confidence: {confidence:.2f})")
            
            # Strategy 2: Look for 10-digit sequences (might be missing GHA prefix)
            for analysis, source in [(back_analysis, 'back'), (front_analysis, 'front')]:
                if 'Blocks' in analysis:
                    for block in analysis['Blocks']:
                        if block.get('BlockType') == 'LINE' and 'Text' in block:
                            text = block['Text'].strip()
                            confidence = block.get('Confidence', 0.0)
                            
                            # Look for 10-digit sequences
                            digits_only = re.sub(r'[^0-9]', '', text)
                            if len(digits_only) == 10:
                                ghana_number = f"GHA-{digits_only[:9]}-{digits_only[9]}"
                                corrected_number = self._correct_ocr_errors(ghana_number)
                                
                                candidates.append({
                                    'number': corrected_number,
                                    'confidence': confidence * 0.8,  # Lower confidence for inferred format
                                    'source': source,
                                    'original_text': text
                                })
            
            # Return best candidate based on confidence and source priority
            if candidates:
                # Prioritize back image (where ID number usually appears)
                back_candidates = [c for c in candidates if c['source'] == 'back']
                if back_candidates:
                    best_candidate = max(back_candidates, key=lambda x: x['confidence'])
                else:
                    best_candidate = max(candidates, key=lambda x: x['confidence'])
                
                logger.info(f"Selected best Ghana number candidate: '{best_candidate['number']}' from {best_candidate['source']} image")
                return best_candidate['number'], best_candidate['confidence']
            
            return None, 0.0
            
        except Exception as e:
            logger.error(f"Error in enhanced Ghana number extraction: {str(e)}")
            return None, 0.0
    
    def _correct_ocr_errors(self, ghana_number: str) -> str:
        """Correct common OCR errors in Ghana card numbers"""
        try:
            # Common OCR misreadings in Ghana card numbers
            corrections = {
                'B': '6',  # B often misread as 6
                'L': '1',  # L often misread as 1  
                'O': '0',  # O often misread as 0
                'S': '5',  # S often misread as 5
                'I': '1',  # I often misread as 1
                'Z': '2',  # Z often misread as 2
                'G': '6',  # G sometimes misread as 6
                'D': '0',  # D sometimes misread as 0
            }
            
            # Only apply corrections to the numeric part (not the GHA prefix)
            if ghana_number.startswith('GHA-'):
                parts = ghana_number.split('-')
                if len(parts) == 3:
                    # Standard format: GHA-XXXXXXXXX-X
                    prefix = parts[0]  # GHA
                    main_digits = parts[1]  # 9 digits
                    check_digit = parts[2]  # 1 digit
                    
                    # Correct the main digits and check digit
                    corrected_main = ''.join(corrections.get(char, char) for char in main_digits)
                    corrected_check = ''.join(corrections.get(char, char) for char in check_digit)
                    
                    corrected_number = f"{prefix}-{corrected_main}-{corrected_check}"
                    
                elif len(parts) == 2:
                    # Format: GHA-XXXXXXXXXX (missing final dash and check digit)
                    prefix = parts[0]  # GHA
                    all_digits = parts[1]  # All digits together
                    
                    # Apply corrections to all digits
                    corrected_digits = ''.join(corrections.get(char, char) for char in all_digits)
                    
                    # Try to format properly if we have 10 characters (9 + 1 check digit)
                    if len(corrected_digits) == 10:
                        corrected_number = f"{prefix}-{corrected_digits[:9]}-{corrected_digits[9]}"
                    else:
                        corrected_number = f"{prefix}-{corrected_digits}"
                    
                else:
                    # Unexpected format, just apply corrections to the whole string
                    corrected_number = ''.join(corrections.get(char, char) if char not in ['G', 'H', 'A', '-'] else char for char in ghana_number)
                
                if corrected_number != ghana_number:
                    logger.info(f"OCR correction applied: '{ghana_number}' → '{corrected_number}'")
                
                return corrected_number
            
            return ghana_number
            
        except Exception as e:
            logger.error(f"Error correcting OCR errors: {str(e)}")
            return ghana_number
    
    def _find_additional_names_in_text(self, analysis_result: Dict[str, Any], known_firstname: str, known_surname: str) -> str:
        """Find additional names in raw text that weren't captured in structured fields"""
        try:
            additional_names = []
            
            # Get all text blocks from front image
            if 'Blocks' in analysis_result:
                for block in analysis_result['Blocks']:
                    if block.get('BlockType') == 'LINE' and 'Text' in block:
                        text = block['Text'].strip()
                        confidence = block.get('Confidence', 0.0)
                        
                        # Only consider high confidence text
                        if confidence > 70:
                            words = text.upper().split()
                            
                            # Look for lines that contain the first name and have additional words
                            if known_firstname.upper() in text.upper() and len(words) > 1:
                                
                                # Method 1: Look for text with both first and last name
                                if known_surname.upper() in text.upper():
                                    try:
                                        first_idx = words.index(known_firstname.upper())
                                        last_idx = words.index(known_surname.upper())
                                        
                                        if last_idx > first_idx + 1:
                                            # Words between first and last name
                                            middle_words = words[first_idx + 1:last_idx]
                                            name_words = [w for w in middle_words if w.isalpha() and len(w) > 1]
                                            if name_words:
                                                additional_names.extend(name_words)
                                                logger.info(f"Found middle names in full name line: '{text}' -> {name_words}")
                                    except ValueError:
                                        pass
                                
                                # Method 2: Look for text that starts with first name and has more words
                                else:
                                    try:
                                        first_idx = words.index(known_firstname.upper())
                                        if first_idx == 0 and len(words) > 1:
                                            # Line starts with first name, get additional words
                                            remaining_words = words[1:]
                                            # Filter out common non-name words and single characters
                                            name_words = [w for w in remaining_words 
                                                        if w.isalpha() and len(w) > 1 
                                                        and w not in ['DE', 'THE', 'AND', 'OF']]
                                            if name_words:
                                                additional_names.extend(name_words)
                                                logger.info(f"Found additional names after first name: '{text}' -> {name_words}")
                                    except ValueError:
                                        pass
            
            # Return unique additional names
            unique_names = []
            for name in additional_names:
                if name.title() not in unique_names:
                    unique_names.append(name.title())
            
            return ' '.join(unique_names) if unique_names else ''
            
        except Exception as e:
            logger.error(f"Error finding additional names in text: {str(e)}")
            return ''

    def _standardize_ghana_number(self, raw_number: str) -> str:
        """Standardize Ghana card number format"""
        try:
            # Remove all non-alphanumeric characters
            clean = ''.join(c for c in raw_number if c.isalnum())
            
            # Handle different formats
            if clean.upper().startswith('GHA'):
                digits = clean[3:]
                if len(digits) >= 10:
                    return f"GHA-{digits[:9]}-{digits[9]}"
                else:
                    return f"GHA-{digits}"
            elif len(clean) == 10 and clean.isdigit():
                return f"GHA-{clean[:9]}-{clean[9]}"
            else:
                return raw_number
                
        except Exception as e:
            logger.error(f"Error standardizing Ghana number: {str(e)}")
            return raw_number
    
    def _extract_identity_fields(self, analysis_result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Extract identity fields from Textract analysis result"""
        fields = {}
        
        try:
            if 'IdentityDocuments' in analysis_result:
                for document in analysis_result['IdentityDocuments']:
                    if 'IdentityDocumentFields' in document:
                        for field in document['IdentityDocumentFields']:
                            field_type = field.get('Type', {}).get('Text', '')
                            field_value = field.get('ValueDetection', {}).get('Text', '')
                            field_confidence = field.get('ValueDetection', {}).get('Confidence', 0.0)
                            
                            if field_type and field_value:
                                fields[field_type] = {
                                    'value': field_value,
                                    'confidence': field_confidence
                                }
            
            return fields
            
        except Exception as e:
            logger.error(f"Error extracting identity fields: {str(e)}")
            return fields
    
    def _extract_ghana_number_from_text(self, analysis_result: Dict[str, Any]) -> tuple[str, float]:
        """
        Extract Ghana card number from all detected text using pattern matching
        Returns: (ghana_card_number, confidence)
        """
        try:
            all_text_blocks = []
            
            # Extract all text from Textract response
            if 'IdentityDocuments' in analysis_result:
                for document in analysis_result['IdentityDocuments']:
                    # Get text from identity document fields
                    if 'IdentityDocumentFields' in document:
                        for field in document['IdentityDocumentFields']:
                            if 'ValueDetection' in field and field['ValueDetection'].get('Text'):
                                text = field['ValueDetection']['Text']
                                confidence = field['ValueDetection'].get('Confidence', 0.0)
                                all_text_blocks.append((text, confidence))
                    
                    # Also check if there are any text blocks in the document
                    if 'Blocks' in document:
                        for block in document['Blocks']:
                            if block.get('BlockType') == 'LINE' and block.get('Text'):
                                text = block['Text']
                                confidence = block.get('Confidence', 0.0)
                                all_text_blocks.append((text, confidence))
            
            # Also check top-level Blocks if available
            if 'Blocks' in analysis_result:
                for block in analysis_result['Blocks']:
                    if block.get('BlockType') == 'LINE' and block.get('Text'):
                        text = block['Text']
                        confidence = block.get('Confidence', 0.0)
                        all_text_blocks.append((text, confidence))
            
            # Pattern matching for Ghana card number format: GHA-XXXXXXXXX-X
            import re
            ghana_patterns = [
                # Full format: GHA-725499847-1
                r'GHA[-\s]*(\d{9})[-\s]*(\d{1})',
                # Spaces or other separators: GHA 725499847 1
                r'GHA[^\d]*(\d{9})[^\d]*(\d{1})',
                # Without separators: GHA7254998471
                r'GHA(\d{9})(\d{1})',
                # Just the number part if GHA is separate: 725499847-1
                r'^(\d{9})[-\s]*(\d{1})$'
            ]
            
            best_match = None
            best_confidence = 0.0
            
            for text, confidence in all_text_blocks:
                text_clean = text.strip().upper()
                logger.debug(f"Checking text block: '{text_clean}' (confidence: {confidence})")
                
                for pattern in ghana_patterns:
                    match = re.search(pattern, text_clean)
                    if match:
                        if len(match.groups()) == 2:
                            # Format: GHA-XXXXXXXXX-X
                            ghana_number = f"GHA-{match.group(1)}-{match.group(2)}"
                        else:
                            # Fallback
                            ghana_number = text_clean
                        
                        if confidence > best_confidence:
                            best_match = ghana_number
                            best_confidence = confidence
                            logger.info(f"Found Ghana card number pattern: {ghana_number} (confidence: {confidence})")
            
            return best_match, best_confidence
            
        except Exception as e:
            logger.error(f"Error in pattern matching for Ghana card number: {str(e)}")
            return None, 0.0
    
    def _format_ghana_card_number(self, card_number: str) -> str:
        """Format Ghana Card number to standard format GHA-XXXXXXXXX-X (9 digits + 1 check digit)"""
        try:
            # Remove all non-alphanumeric characters
            clean_number = ''.join(c for c in card_number if c.isalnum())
            
            # Check if it starts with GHA
            if clean_number.upper().startswith('GHA'):
                digits = clean_number[3:]  # Remove GHA prefix
            else:
                digits = clean_number
            
            # Format as GHA-XXXXXXXXX-X if we have exactly 10 digits (9 + 1 check digit)
            if len(digits) == 10 and digits.isdigit():
                return f"GHA-{digits[:9]}-{digits[9]}"
            elif len(digits) >= 10:
                # Take first 10 digits if more than 10
                return f"GHA-{digits[:9]}-{digits[9]}"
            else:
                # Return with GHA prefix if not enough digits
                return f"GHA-{digits}"
                
        except Exception as e:
            logger.error(f"Error formatting Ghana Card number: {str(e)}")
            return card_number
    
    def _get_average_confidence(self, analysis_result: Dict[str, Any]) -> float:
        """Calculate average confidence from Textract analysis result"""
        try:
            confidences = []
            
            if 'IdentityDocuments' in analysis_result:
                for document in analysis_result['IdentityDocuments']:
                    if 'IdentityDocumentFields' in document:
                        for field in document['IdentityDocumentFields']:
                            confidence = field.get('ValueDetection', {}).get('Confidence', 0.0)
                            if confidence > 0:
                                confidences.append(confidence)
            
            return sum(confidences) / len(confidences) if confidences else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating average confidence: {str(e)}")
            return 0.0
    
    def _cleanup_s3_files(self, s3_keys: list):
        """Clean up uploaded S3 files (optional)"""
        try:
            for key in s3_keys:
                self.s3_client.delete_object(Bucket=self.s3_bucket, Key=key)
            logger.info(f"Cleaned up {len(s3_keys)} S3 files")
        except Exception as e:
            logger.warning(f"Failed to clean up S3 files: {str(e)}")

# Global instance
aws_textract_service = AWSTextractService()