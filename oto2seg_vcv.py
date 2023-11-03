from __future__ import annotations
import re
from os import path
from wave import open as open_wave

from functions import OtoInfo, get_hiragana_info, read_oto

def generate_articulation_seg_data(oto_list: list[OtoInfo], wav_length: float) -> list[list[str, float, float]]:
    phoneme_list = []

    oto_index = 0
    for oto_item in oto_list:
        if re.match(r"^[aiueonN] \-", oto_item.alias): # End of sentence
            phoneme_list.append(['Sil', oto_item.preutterance]) # Preutterance is the end of the previous syllable
        elif re.match(r"^[\-aiueonN] [ぁ-ゔァ-・]+", oto_item.alias): # VCV entry
            hatsuon = re.match(r"^[\-aiueonN] ([ぁ-ゔァ-・]+)", oto_item.alias).group(1)

            if hatsuon == "を":
                continue # Skip を, it's dumplicated with お

            hatsuon_info = get_hiragana_info(hatsuon)

            if not hatsuon_info:
                print(f"Warning: Could not find hiragana info for {hatsuon}, skipping.")
                continue
            
            phonemes = hatsuon_info["phoneme"].split(" ")
            phonemes_len = len(phonemes)
            if phonemes_len == 1:
                # Monophone
                phoneme_list.append([phonemes[0], oto_item.preutterance])
            elif phonemes_len == 2:
                # Overlap is the start of the consonant, and preutterance is the start of the vowel
                if phonemes[0] == "h" and oto_index != 0: # Fix は in the middle of a sentence
                    phonemes[0] = "h\\"

                phoneme_list.append([phonemes[0], oto_item.overlap])
                phoneme_list.append([phonemes[1], oto_item.preutterance])
            else:
                print(f"Warning: Hiragana {hatsuon} has {phonemes_len} phonemes, skipping.")

        oto_index += 1

    # Sort the phoneme list by start time
    phoneme_list.sort(key=lambda x: x[1])

    # Add Sil at the start and end
    first_phoneme_start = phoneme_list[0][1]
    if first_phoneme_start < 40: # Keep at least 40ms of silence at the start
        phoneme_list[0][1] = 40
        first_phoneme_start = 40

    phoneme_list.insert(0, ['Sil', 0])
    phoneme_list.insert(1, ['Sil', first_phoneme_start - 20])

    last_phoneme_end = phoneme_list[-1][1]
    if last_phoneme_end > wav_length - 20: # Keep at least 20ms of silence at the end
        phoneme_list[-1][1] = wav_length - 20
        last_phoneme_end = wav_length - 20

    phoneme_list.append(['Sil', last_phoneme_end + 20])
    phoneme_list.append(['Sil', wav_length])

    seg_info = []
    for i in range(0, len(phoneme_list) - 1):
        seg_info.append([
            phoneme_list[i][0],
            phoneme_list[i][1] / 1000,
            phoneme_list[i + 1][1] / 1000,
        ])

    return seg_info

def xsampa_is_vowel(phoneme: str) -> bool:
    return phoneme in ["a", "i", "M", "e", "o", "N\\"]

def generate_articulation_seg_file(seg_info: list[list[str, float, float]]) -> str:
    content = [
        "nPhonemes %d" % len(seg_info),
        "articulationsAreStationaries = 0",
        "phoneme		BeginTime		EndTime",
        "==================================================="
    ]

    for phoneme, begin_time, end_time in seg_info:
        content.append("%s\t\t%.6f\t\t%.6f" % (phoneme, begin_time, end_time))

    return "\n".join(content) + "\n"

def generate_articulation_trans_file(seg_info: list[list[str, float, float]]) -> str:
    content = []

    phoneme_list = []
    for i in range(1, len(seg_info) - 1):
        phoneme_list.append(seg_info[i][0])
    
    content.append(" ".join(phoneme_list))

    seg_len = len(seg_info)

    i = 2
    while i < seg_len - 1:
        if i > 2 and i < seg_len - 2 and not xsampa_is_vowel(seg_info[i][0]): # Force first and second items be Sil-C, C-V
            content.append("[%s %s %s]" % (seg_info[i - 1][0], seg_info[i][0], seg_info[i + 1][0]))
            i += 1
        else:
            content.append("[%s %s]" % (seg_info[i - 1][0], seg_info[i][0]))

        i += 1

    return "\n".join(content)

def generate_articulation_from_oto(oto_dict: dict[str, list[OtoInfo]], output_dir: str) -> str:
    """Converts an oto.ini dictionary to a .seg file."""
    for wav_file, oto_list in oto_dict.items():
        base_name = path.splitext(path.basename(wav_file))[0]
        wav_file_resolved = oto_list[0].wav_file
        with open_wave(wav_file_resolved, 'rb') as wav:
            wav_params = wav.getparams()
            wav_length = wav_params.nframes / wav_params.framerate * 1000

        seg_info = generate_articulation_seg_data(oto_list, wav_length)
        seg_file_content = generate_articulation_seg_file(seg_info)

        seg_file = path.join(output_dir, base_name + ".seg")
        with open(seg_file, "w", encoding="utf-8") as f:
            f.write(seg_file_content)

        trans_file_content = generate_articulation_trans_file(seg_info)
        trans_file = path.join(output_dir, base_name + ".trans")
        with open(trans_file, "w", encoding="utf-8") as f:
            f.write(trans_file_content)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: oto2seg.py <oto.ini> <output articulation dir>")
        sys.exit(1)
    
    oto_dict = read_oto(sys.argv[1])
    generate_articulation_from_oto(oto_dict, sys.argv[2])