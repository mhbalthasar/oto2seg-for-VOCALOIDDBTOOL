from __future__ import annotations
import math
import re
from os import path
from typing import TypedDict
from wave import open as open_wave
from pydub import AudioSegment

from functions import *
from phoneme import *

class PhonemeStream:
    def __init__(self, item_list: list[JPhonemeMapItem]):
        self.item_list = [item for item in item_list if item]
        self.item_len = len(item_list)
        self.cv_seek = 0
        self.vc_seek = 0

    def next_cv(self, romaji: str) -> bool:
        while self.cv_seek < self.item_len:
            finded_item = None
            if self.item_list[self.cv_seek]["romaji"] == romaji:
                finded_item = self.item_list[self.cv_seek]
            else:
                self.cv_seek += 1
                self.vc_seek += 1

            if finded_item:
                return finded_item
            
        return False
    
    def next_vc(self, romaji: str) -> bool:
        vowel, consonant = romaji.split(" ", 1)
        if vowel == "-" and self.vc_seek == 0: # Beginning consonant
            return self.item_list[0]
        
        while self.vc_seek < self.item_len:
            if self.item_len == 0:
                self.item_len += 1
            
            finded_item = None
            phoneme_item = self.item_list[self.vc_seek]
            prev_phoneme_item = self.item_list[self.vc_seek - 1]
            if prev_phoneme_item["romaji"].endswith(vowel) and phoneme_item["romaji"].startswith(consonant):
                finded_item = self.item_list[self.vc_seek]
            else:
                self.vc_seek += 1
                self.cv_seek += 1

            if finded_item:
                return finded_item
            
        return False

def detect_cvvc_initial_mode(oto_dict: dict[str, list[OtoInfo]]):
    """Detects the CV mode of an oto dictionary."""
    for oto_list in oto_dict.values():
        for oto_item in oto_list:
            if re.match(r"^- (s ?a|さ)", oto_item.alias):
                return "rcv"
    
    return "rccv"

class ArticulationSegmentInfo(TypedDict):
    type: str
    phonemes: list[str, str]
    boundaries: list[list[str, float, float]]

class SegmentInfo:
    wav_offset: float
    wav_cutoff: float
    phoneme_list: list[list[str, float]]
    art_seg_list: list[ArticulationSegmentInfo]

    def copy(self):
        new_seg_info = SegmentInfo()
        new_seg_info.wav_offset = self.wav_offset
        new_seg_info.wav_cutoff = self.wav_cutoff
        new_seg_info.phoneme_list = []

        for phoneme in self.phoneme_list:
            new_seg_info.phoneme_list.append(phoneme.copy())

        new_seg_info.art_seg_list = []

        for art_seg in self.art_seg_list:
            new_art_seg = ArticulationSegmentInfo()
            new_art_seg["type"] = art_seg["type"]
            new_art_seg["phonemes"] = art_seg["phonemes"].copy()
            new_art_seg["boundaries"] = art_seg["boundaries"].copy()
            new_seg_info.art_seg_list.append(new_art_seg)

        return new_seg_info
    
    def replace_phoneme(self, old_phonemes: list[str], new_phonemes: list[str]):
        new_seg_info = self.copy()

        for i in range(0, len(new_seg_info.phoneme_list)):
            phoneme = new_seg_info.phoneme_list[i]
            if phoneme[0] in old_phonemes:
                phoneme[0] = new_phonemes[old_phonemes.index(phoneme[0])]

        for art_seg in new_seg_info.art_seg_list:
            for i in range(0, len(art_seg["phonemes"])):
                phoneme = art_seg["phonemes"][i]
                if phoneme in old_phonemes:
                    art_seg["phonemes"][i] = new_phonemes[old_phonemes.index(phoneme)]

        return new_seg_info


def get_segment_file_name(seg_info: SegmentInfo):
    if len(seg_info.art_seg_list) == 2 and seg_info.art_seg_list[0]["type"] == "rc" and seg_info.art_seg_list[1]["type"] == "cv":
        prefix = "rcv_"
    elif len(seg_info.art_seg_list) == 1:
        prefix = seg_info.art_seg_list[0]["type"] + "_"
    else:
        prefix = "unknown_"

    phonemes = [escape_xsampa(item[0]) for item in seg_info.phoneme_list]
    return prefix + "_".join(phonemes)

def quantize_boundary(boundaries: list[float]) -> list[float]:
    sample_rate = 44100
    n_boundary = len(boundaries)
    for i in range(0, n_boundary):
        if i == 0:
            boundaries[i] = math.floor(boundaries[i] / 1000 * sample_rate) * 1000 / sample_rate
        elif i == n_boundary - 1:
            boundaries[i] = math.ceil(boundaries[i] / 1000 * sample_rate) * 1000 / sample_rate
        else:
            boundaries[i] = math.floor(boundaries[i] / 1000 * sample_rate) * 1000 / sample_rate

    min_length = 10
    for i in range(1, n_boundary):
        if boundaries[i] - boundaries[i - 1] < min_length:
            boundaries[i - 1] = boundaries[i] - min_length

    return boundaries

def generate_articulation_segment_info(oto_list: list[OtoInfo], cvvc_initial_mode: str, wav_length: float) -> list[SegmentInfo]:
    seg_info_list: list[SegmentInfo] = []
    
    for oto_item in oto_list:
        try:
            entry_phoneme_info = get_oto_entry_phoneme_info(oto_item)
            
            seg_info = SegmentInfo()
            seg_info.wav_offset = oto_item.offset
            seg_info.wav_cutoff = oto_item.cutoff
            if entry_phoneme_info.type == "rcv":
                seg_info.wav_cutoff = oto_item.preutterance

                seg_info.phoneme_list = [
                    ["Sil", oto_item.offset - 20, oto_item.offset],
                    [entry_phoneme_info.phoneme_list[0], oto_item.offset, oto_item.preutterance],
                    # [phoneme_info["phoneme"][1], oto_item.preutterance, oto_item.cutoff],
                ]
                seg_info.art_seg_list = [
                    {
                        "type": "rc",
                        "phonemes": ["Sil", entry_phoneme_info.phoneme_list[0]],
                        "boundaries": quantize_boundary([oto_item.offset - 20, oto_item.offset, oto_item.overlap]),
                    },
                ]
            elif entry_phoneme_info.type == "rv":
                seg_info.phoneme_list = [
                    ["Sil", oto_item.preutterance - 20, oto_item.preutterance],
                    [entry_phoneme_info.phoneme_list[0], oto_item.preutterance, oto_item.cutoff],
                ]
                seg_info.art_seg_list = [
                    {
                        "type": "rv",
                        "phonemes": ["Sil", entry_phoneme_info.phoneme_list[0]],
                        "boundaries": quantize_boundary([oto_item.preutterance - 20, oto_item.preutterance, oto_item.consonant]),
                    }
                ]
            elif entry_phoneme_info.type == "rc":
                if entry_phoneme_info.phoneme_list[0] in plosive_consonant_list:
                    consonant_start = oto_item.consonant
                else:
                    consonant_start = oto_item.offset

                seg_info.phoneme_list = [
                    ["Sil", consonant_start - 20, consonant_start],
                    [entry_phoneme_info.phoneme_list[0], consonant_start, oto_item.cutoff],
                ]
                seg_info.art_seg_list = [
                    {
                        "type": "rc",
                        "phonemes": ["Sil", entry_phoneme_info.phoneme_list[0]],
                        "boundaries": quantize_boundary([consonant_start - 20, consonant_start, oto_item.cutoff]),
                    }
                ]
            elif entry_phoneme_info.type == "vv":
                seg_info.phoneme_list = [
                    [entry_phoneme_info.phoneme_list[0], oto_item.offset, oto_item.preutterance],
                    [entry_phoneme_info.phoneme_list[1], oto_item.preutterance, oto_item.consonant],
                ]

                seg_info.art_seg_list = [
                    {
                        "type": "vv",
                        "phonemes": [entry_phoneme_info.phoneme_list[0], entry_phoneme_info.phoneme_list[1]],
                        "boundaries": quantize_boundary([oto_item.offset, oto_item.preutterance, oto_item.consonant]),
                    }
                ]
            elif entry_phoneme_info.type == "cv":
                consonant = entry_phoneme_info.phoneme_list[0]
                if consonant in plosive_consonant_list:
                    consonant_start = oto_item.overlap
                elif oto_item.overlap > oto_item.offset:
                    consonant_start = oto_item.offset + ((oto_item.overlap - oto_item.offset) / 2)
                else:
                    consonant_start = oto_item.offset

                seg_info.phoneme_list = [
                    [entry_phoneme_info.phoneme_list[0], consonant_start, oto_item.preutterance],
                    [entry_phoneme_info.phoneme_list[1], oto_item.preutterance, oto_item.consonant],
                ]

                seg_info.art_seg_list = [
                    {
                        "type": "cv",
                        "phonemes": [entry_phoneme_info.phoneme_list[0], entry_phoneme_info.phoneme_list[1]],
                        "boundaries": quantize_boundary([consonant_start, oto_item.preutterance, oto_item.consonant]),
                    }
                ]
            elif entry_phoneme_info.type == "vc":
                consonant = entry_phoneme_info.phoneme_list[1]
                consonant_end = oto_item.consonant + ((oto_item.cutoff - oto_item.consonant) / 2)
                
                seg_info.phoneme_list = [
                    [entry_phoneme_info.phoneme_list[0], oto_item.offset, oto_item.preutterance],
                    [entry_phoneme_info.phoneme_list[1], oto_item.preutterance, consonant_end],
                ]

                seg_info.art_seg_list = [
                    {
                        "type": "vc",
                        "phonemes": [entry_phoneme_info.phoneme_list[0], entry_phoneme_info.phoneme_list[1]],
                        "boundaries": quantize_boundary([oto_item.offset, oto_item.preutterance, consonant_end]),
                    }
                ]
            elif entry_phoneme_info.type == "vr":
                seg_info.phoneme_list = [
                    [entry_phoneme_info.phoneme_list[0], oto_item.offset, oto_item.preutterance],
                    ["Sil", oto_item.preutterance, oto_item.preutterance + 20],
                ]

                seg_info.art_seg_list = [
                    {
                        "type": "vr",
                        "phonemes": [entry_phoneme_info.phoneme_list[0], "Sil"],
                        "boundaries": quantize_boundary([oto_item.overlap, oto_item.preutterance, oto_item.preutterance + 20]),
                    }
                ]
            else:
                raise Exception("Unknown phoneme type: %s" % (entry_phoneme_info.type,))

            seg_info_list.append(seg_info)
        except Exception as e:
            print("Warning: Failed to parse %s: %s" % (oto_item.alias, e))
    
    return seg_info_list

def generate_articulation_seg_file(phoneme_list: list[list], cutoff_pos: int, wav_length: int) -> str:
    content = [
        "nPhonemes %d" % (len(phoneme_list) + 2,), # Add 2 Sil
        "articulationsAreStationaries = 0",
        "phoneme		BeginTime		EndTime",
        "==================================================="
    ]

    content.append("%s\t\t%.6f\t\t%.6f" % ("Sil", 0, phoneme_list[0][1] / 1000))

    for i in range(0, len(phoneme_list)):
        phoneme_info = phoneme_list[i]
        phoneme_name = phoneme_info[0]
        begin_time = phoneme_info[1] / 1000
        if i == len(phoneme_list) - 1:
            end_time = cutoff_pos / 1000
        else:
            end_time = phoneme_list[i + 1][1] / 1000

        content.append("%s\t\t%.6f\t\t%.6f" % (phoneme_name, begin_time, end_time))

    content.append("%s\t\t%.6f\t\t%.6f" % ("Sil", cutoff_pos / 1000, wav_length / 1000))

    return "\n".join(content) + "\n"

def generate_articulation_trans_file(seg_info: list[list]) -> str:
    content = []

    phoneme_list = []
    for i in range(0, len(seg_info)):
        phoneme_list.append(seg_info[i][0])
    
    content.append(" ".join(phoneme_list))

    for i in range(0, len(seg_info) - 1):
        content.append("[%s %s]" % (seg_info[i][0], seg_info[i + 1][0]))

    return "\n".join(content)

def generate_articulation_as_files(art_seg_list: list[ArticulationSegmentInfo], wav_samples: int) -> str:
    as_content_list = []
    for art_seg_info in art_seg_list:
        content = [
            "nphone art segmentation",
            "{",
            '\tphns: ["' + ('", "'.join(art_seg_info["phonemes"])) + '"];',
            '\tcut offset: 0;',
            '\tcut length: %d;' % wav_samples,
        ]

        boundaries_str = [("%.9f" % (item / 1000)) for item in art_seg_info["boundaries"]]
        content.append('\tboundaries: [' + ', '.join(boundaries_str) + '];')
        
        content.append('\trevised: false;')
        
        voiced_str = []
        for phoneme in art_seg_info["phonemes"]:
            if phoneme in unvoiced_consonant_list:
                voiced_str.append("false")
            else:
                voiced_str.append("true")

        content.append('\tvoiced: [' + ', '.join(voiced_str) + '];')

        content.append("};")
        content.append("")

        as_content_list.append("\n".join(content))

    return as_content_list


def generate_articulation_files(wav_file: str, seg_info: SegmentInfo, output_dir: str) -> str:
    bleed_time = 100

    file_name = get_segment_file_name(seg_info)
    print("Generating %s..." % file_name)

    append_silent_start = 0
    append_silent_end = 0
    seg_wav_length = seg_info.wav_cutoff - seg_info.wav_offset + bleed_time * 2

    time_delta = 0

    if seg_info.wav_offset < bleed_time:
        append_silent_start = bleed_time - seg_info.wav_offset
        time_delta += append_silent_start
    else:
        time_delta = -1 * (seg_info.wav_offset - bleed_time)


    # Relative data
    relative_wav_offset = seg_info.wav_offset + time_delta
    relative_wav_cutoff = seg_info.wav_cutoff + time_delta

    phoneme_list = []
    for phoneme in seg_info.phoneme_list:
        phoneme_list.append([
            phoneme[0],
            phoneme[1] + time_delta,
            phoneme[2] + time_delta,
        ])
    
    art_seg_list = []
    for art_seg in seg_info.art_seg_list:
        art_seg_list.append({
            "type": art_seg["type"],
            "phonemes": art_seg["phonemes"],
            "boundaries": [boundary + time_delta for boundary in art_seg["boundaries"]],
        })

    with open_wave(wav_file, 'rb') as wav:
        wav_length = wav.getnframes() / wav.getframerate() * 1000

    if seg_info.wav_cutoff + bleed_time > wav_length:
        append_silent_end = seg_info.wav_cutoff + bleed_time - wav_length

    # Generate trans file
    trans_content = generate_articulation_trans_file(phoneme_list)
    output_trans_file = path.join(output_dir, file_name + ".trans")
    with open(output_trans_file, "w", encoding="utf-8") as f:
        f.write(trans_content)
        
    # Generate wav file
    input_sound = AudioSegment.from_wav(wav_file)
    wav_start_time = max(0, seg_info.wav_offset - bleed_time)
    wav_end_time = min(wav_length, seg_info.wav_cutoff + bleed_time)
    output_sound: AudioSegment = input_sound[wav_start_time:wav_end_time]

    if append_silent_start > 0:
        output_sound = AudioSegment.silent(duration=append_silent_start) + output_sound
    if append_silent_end > 0:
        output_sound = output_sound + AudioSegment.silent(duration=append_silent_end)

    output_wav_file = path.join(output_dir, file_name + ".wav")
    output_sound.export(output_wav_file, format="wav")

    output_wav_length = output_sound.duration_seconds * 1000
    output_wav_frames = output_sound.frame_count()

    # Generate seg file
    seg_content = generate_articulation_seg_file(phoneme_list, relative_wav_cutoff, output_wav_length)
    output_seg_file = path.join(output_dir, file_name + ".seg")
    with open(output_seg_file, "w", encoding="utf-8") as f:
        f.write(seg_content)
        
    # Generate as file
    as_content_list = generate_articulation_as_files(art_seg_list, output_wav_frames)
    for i in range(0, len(as_content_list)):
        output_as_file = path.join(output_dir, file_name + ".as%d" % i)
        with open(output_as_file, "w", encoding="utf-8") as f:
            f.write(as_content_list[i])

def find_alternative_vc(vc_name: str, vc_hit_list: map) -> str:
    """Finds an alternative VC for a VC name."""
    vowel, consonant = vc_name.split(" ", 1)

    vowel_variants = get_vowel_variants(vowel)
    consonant_variants = get_consonant_variants(consonant)

    for alter_consonant in consonant_variants:
        for alter_vowel in vowel_variants:
            alter_vc_name = alter_vowel + " " + alter_consonant
            if alter_vc_name in vc_hit_list:
                return alter_vc_name
            
    return ""

def find_alternative_vr(vowel: str, vr_hit_list: map) -> str:
    """Finds an alternative VR for a VR name."""
    vowel_variants = get_vowel_variants(vowel)

    for alter_vowel in vowel_variants:
        alter_vr_name = alter_vowel + " -"
        if alter_vr_name in vr_hit_list:
            return alter_vowel

    return ""

def generate_articulation_from_oto(oto_dict: dict[str, list[OtoInfo]], cvvc_initial_mode: str, output_dir: str) -> str:
    """Converts an oto.ini dictionary to a .seg file."""
    cvvc_map = {}
    full_seg_info_list = []
    
    for wav_file, oto_list in oto_dict.items():
        if len(oto_list) == 0:
            continue

        base_name = path.splitext(path.basename(wav_file))[0]
        wav_file_resolved = oto_list[0].wav_file
        with open_wave(wav_file_resolved, 'rb') as wav:
            wav_params = wav.getparams()
            wav_length = wav_params.nframes / wav_params.framerate * 1000

        seg_info_list = generate_articulation_segment_info(oto_list, cvvc_initial_mode, wav_length)
        
        for seg_info in seg_info_list:
            generate_articulation_files(wav_file_resolved, seg_info, output_dir)

            for art_seg in seg_info.art_seg_list:
                if art_seg["type"] == "vc" or art_seg["type"] == "cv":
                    cvvc_map[" ".join(art_seg["phonemes"])] = {
                        "seg_info": seg_info,
                        "wav_file": wav_file_resolved
                    }
                elif art_seg["type"] == "vr":
                    cvvc_map[art_seg["phonemes"][0] + " -"] = {
                        "seg_info": seg_info,
                        "wav_file": wav_file_resolved
                    }

    vc_miss_list = []
    vr_miss_list = []
    for vc in vc_list:
        if vc not in cvvc_map:
            vc_miss_list.append(vc)

    for vr in vr_list:
        vr_name = vr + " -"
        if vr_name not in cvvc_map:
            vr_miss_list.append(vr)

    print("Missing VC: " + ", ".join(vc_miss_list))
    print("Missing VR: " + ", ".join(vr_miss_list))

    # Generate missing VC from alternative consonant
    for vc_name in vc_miss_list:
        vowel, consonant = vc_name.split(" ", 1)

        alternative_vc = find_alternative_vc(vc_name, cvvc_map)
        if alternative_vc:
            print("Alternative VC for %s: %s" % (vc_name, alternative_vc))

            alternative_v, alternative_c = alternative_vc.split(" ", 1)
            
            alternative_info = cvvc_map[alternative_vc]
            new_seg_info: SegmentInfo = alternative_info["seg_info"].replace_phoneme([alternative_c], [consonant])
            
            generate_articulation_files(alternative_info["wav_file"], new_seg_info, output_dir)
        else:
            print("Warning: Could not find alternative VC for %s, skip this line." % vc_name)

    # Generate missing VR from alternative vowel
    for vowel in vr_miss_list:
        alternative_vr = find_alternative_vr(vowel, cvvc_map)
        if alternative_vr:
            print("Alternative VR for %s: %s" % (vowel, alternative_vr))

            alternative_info = cvvc_map[alternative_vr + " -"]
            new_seg_info: SegmentInfo = alternative_info["seg_info"].replace_phoneme([alternative_vr], [vowel])
            
            generate_articulation_files(alternative_info["wav_file"], new_seg_info, output_dir)
        else:
            print("Warning: Could not find alternative VR for %s, skip this line." % vowel)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: oto2seg.py <oto.ini> <output articulation dir>")
        exit(1)
    
    oto_dict = read_oto(sys.argv[1])
    cvvc_initial_mode = detect_cvvc_initial_mode(oto_dict)

    if cvvc_initial_mode == "rcv":
        print("CVVC Type: R-CV-VC-V-R")
    else:
        print("CVVC Type: R-C-CV-VC-V-R")

    generate_articulation_from_oto(oto_dict, cvvc_initial_mode, sys.argv[2])