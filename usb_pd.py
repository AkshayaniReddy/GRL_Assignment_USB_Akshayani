import re
import json
import os
import pdfplumber
import networkx as nx
import matplotlib.pyplot as plt
import argparse
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher

class USBPDSpecParser:   
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc_title = os.path.splitext(os.path.basename(pdf_path))[0]
        self.toc_entries = []
        self.document_chunks = []
        self.knowledge_graph = nx.DiGraph()
        self.validation_report = {}

    def extract_toc(self) -> List[Dict]:
        """Extract and parse Table of Contents from any page in the document"""
        with pdfplumber.open(self.pdf_path) as pdf:
            toc_pages = []
            visited_pages = set()

            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue

                lines = text.split('\n')
                # Check for "Table of Contents" keyword or numbered ToC-like lines
                has_toc_keyword = "Table of Contents" in text or "CONTENTS" in text
                toc_like_lines = sum(bool(re.match(r'^\s*\d+(\.\d+)*\s+.+\.+\s+\d+$', l)) for l in lines)

                if has_toc_keyword or toc_like_lines >= 5:
                    # Avoid duplicates
                    if i not in visited_pages:
                        toc_pages.extend(p.extract_text() for p in pdf.pages[i:i+5])
                        visited_pages.update(range(i, min(i+5, len(pdf.pages))))
            
            if not toc_pages:
                raise ValueError("No Table of Contents pages detected in the document")

            entries = []
            for page_text in toc_pages:
                if not page_text:
                    continue
                for line in page_text.split('\n'):
                    entry = self._parse_toc_line(line)
                    if entry:
                        entries.append(entry)

            # Sort by section ID
            entries.sort(key=lambda x: [int(p) for p in x['section_id'].split('.')])
            self.toc_entries = entries
            return entries


    def _parse_toc_line(self, line: str) -> Optional[Dict]:
        """Parse a single ToC line with improved regex"""
        pattern = r"""
            ^\s*                          # Leading whitespace
            (?P<section_id>\d+(?:\.\d+)*) # Section number (e.g. 2.1.3)
            \s+                           # Whitespace
            (?P<title>.+?)                # Title (non-greedy)
            \s*\.{2,}\s*                  # Dots separator
            (?P<page>\d+)                 # Page number
            \s*$                          # Trailing whitespace
        """
        match = re.search(pattern, line, re.VERBOSE)
        if not match:
            return None
        
        section_id = match.group("section_id")
        title = match.group("title").strip()
        page = int(match.group("page"))
        level = section_id.count('.') + 1
        parent_id = '.'.join(section_id.split('.')[:-1]) if '.' in section_id else None
        
        return {
            "doc_title": self.doc_title,
            "section_id": section_id,
            "title": title,
            "page": page,
            "level": level,
            "parent_id": parent_id,
            "full_path": f"{section_id} {title}"
        }

    def chunk_document(self) -> List[Dict]:
        """Parse full document into logical chunks"""
        current_heading = None
        current_chunk = None
        heading_stack = []
        chunks = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                
                for line in text.split('\n'):
                    # Detect headings (e.g. "2.1.3 Section Title")
                    heading_match = re.match(r'^(\d+(\.\d+)*\s+.+)$', line.strip())
                    if heading_match:
                        # Finalize current chunk
                        if current_chunk:
                            current_chunk['page_range'] = (current_chunk['page_range'][0], page.page_number-1)
                            chunks.append(current_chunk)
                        
                        # Start new chunk
                        full_heading = heading_match.group(1)
                        section_id = full_heading.split()[0]
                        title = ' '.join(full_heading.split()[1:])
                        
                        # Update heading stack
                        level = section_id.count('.') + 1
                        while heading_stack and heading_stack[-1][1] >= level:
                            heading_stack.pop()
                        heading_stack.append((full_heading, level))
                        
                        current_chunk = {
                            "section_path": ' > '.join(h[0] for h in heading_stack),
                            "start_heading": full_heading,
                            "content": "",
                            "tables": [],
                            "figures": [],
                            "page_range": (page.page_number, page.page_number)
                        }
                        current_heading = full_heading
                    elif current_chunk:
                        # Add content to current chunk
                        current_chunk['content'] += line + '\n'
                        
                        # Detect tables and figures
                        if "Table" in line:
                            current_chunk['tables'].append(line.strip())
                        if "Figure" in line:
                            current_chunk['figures'].append(line.strip())
        
        if current_chunk:
            chunks.append(current_chunk)
        
        self.document_chunks = chunks
        return chunks

    def validate_structure(self) -> Dict:
        """Validate chunked content against ToC"""
        toc_sections = {entry['full_path']: entry for entry in self.toc_entries}
        chunked_sections = {chunk['start_heading']: chunk for chunk in self.document_chunks}
        
        # Find matches and mismatches
        matched = []
        missing_from_chunks = []
        extra_in_chunks = []
        
        for toc_path, toc_entry in toc_sections.items():
            if toc_path in chunked_sections:
                matched.append(toc_path)
            else:
                # Try fuzzy matching
                best_match = None
                best_ratio = 0
                for chunk_path in chunked_sections:
                    ratio = SequenceMatcher(None, toc_path, chunk_path).ratio()
                    if ratio > 0.8 and ratio > best_ratio:
                        best_ratio = ratio
                        best_match = chunk_path
                
                if best_match and best_ratio > 0.9:
                    matched.append(toc_path)
                else:
                    missing_from_chunks.append(toc_path)
        
        extra_in_chunks = set(chunked_sections) - set(toc_sections)
        
        # Check ordering
        toc_order = [entry['full_path'] for entry in self.toc_entries]
        chunk_order = [chunk['start_heading'] for chunk in self.document_chunks 
                      if chunk['start_heading'] in toc_order]
        
        out_of_order = []
        for i, (toc_sec, chunk_sec) in enumerate(zip(toc_order, chunk_order)):
            if toc_sec != chunk_sec:
                out_of_order.append({
                    "expected": toc_sec,
                    "found": chunk_sec,
                    "position": i
                })
        
        self.validation_report = {
            "toc_section_count": len(toc_sections),
            "parsed_section_count": len(chunked_sections),
            "matched_sections": matched,
            "missing_sections": missing_from_chunks,
            "extra_sections": list(extra_in_chunks),
            "out_of_order_sections": out_of_order,
            "match_percentage": len(matched)/len(toc_sections)*100 if toc_sections else 0
        }
        
        return self.validation_report

    def save_outputs(self, output_dir: str):
        """Save all outputs to specified directory"""
        os.makedirs(output_dir, exist_ok=True)
        
        # Save ToC
        toc_path = os.path.join(output_dir, "usb_pd.jsonl")
        with open(toc_path, 'w', encoding='utf-8') as f:
            for entry in self.toc_entries:
                f.write(json.dumps(entry) + '\n')
        
       
        return {
            "toc": toc_path,
        }

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='USB PD Specification Parser')
    # parser.add_argument('--input_pdf',default=r"D:\CTS\USB PD3 CTS Q2 2025 OR\USB PD R2.0 V1.3 2017-11-17\USB_PD_R2_0 V1.3.pdf")
    parser.add_argument('--input_pdf',default=r"C:\Users\HP\Downloads\USB_PD_R3_2 V1.1 2024-10.pdf")
    parser.add_argument('--output_dir',default=r'D:\Apps\EYE')
    
    args = parser.parse_args()
    
    try:
        # Verify PDF exists
        if not os.path.exists(args.input_pdf):
            raise FileNotFoundError(f"PDF file not found at: {args.input_pdf}")
        
        print(f"Processing PDF: {args.input_pdf}")
        
        # Initialize and run parser
        parser = USBPDSpecParser(args.input_pdf)
        
        # Step 1: Extract ToC
        print("Extracting Table of Contents...")
        toc = parser.extract_toc()
        
        # Step 2: Logical Chunking
        print("Chunking document content...")
        chunks = parser.chunk_document()
        
        # Step 3: Validate Structure
        print("Validating document structure...")
        report = parser.validate_structure()
               
        # Save all outputs
        print("Saving outputs...")
        outputs = parser.save_outputs(args.output_dir)
        
        # Print summary
        print("\nProcessing complete. Output files:")
        for name, path in outputs.items():
            print(f"- {name}: {os.path.abspath(path)}")
        
        print(f"\nValidation Results:")
        print(f"- Match Percentage: {report['match_percentage']:.1f}%")
        print(f"- Missing Sections: {len(report['missing_sections'])}")
        print(f"- Extra Sections: {len(report['extra_sections'])}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
    
