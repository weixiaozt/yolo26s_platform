"""Native-resolution detection tiles with an immutable original-image split."""
from pathlib import Path
import hashlib
import json
import math
import random
from collections import Counter


def window_positions(length, tile_size, overlap):
    if length <= tile_size:
        return [0]
    step = max(1, round(tile_size * (1 - overlap)))
    positions = list(range(0, length - tile_size + 1, step))
    if positions[-1] != length - tile_size:
        positions.append(length - tile_size)
    return positions


def clip_box(box, x, y, tile_size):
    cls, x1, y1, x2, y2 = box
    left, top = max(x1, x), max(y1, y)
    right, bottom = min(x2, x + tile_size), min(y2, y + tile_size)
    if right <= left or bottom <= top:
        return None
    return cls, left - x, top - y, right - x, bottom - y


def fully_contains(box, x, y, tile_size):
    _, x1, y1, x2, y2 = box
    return x <= x1 and y <= y1 and x2 <= x + tile_size and y2 <= y + tile_size


def tile_detection_dataset(raw_dir, dataset_dir, tile_size=1024, overlap=.25,
                           train_ratio=.8, seed=42, bg_keep_ratio=.25,
                           split_manifest=None, progress_callback=None):
    """Split originals first. Never resize, drop tiny boxes, or subsample validation."""
    from PIL import Image
    raw_dir, dataset_dir = Path(raw_dir), Path(dataset_dir)
    if tile_size < 32 or not 0 <= overlap <= .5 or not 0 <= bg_keep_ratio <= 1:
        raise ValueError('Invalid detection tile configuration')
    originals = sorted(p for p in (raw_dir / 'images').iterdir() if p.is_file())
    if len(originals) < 2:
        raise ValueError('At least two original images are required')
    if split_manifest:
        split_by_stem = split_manifest['split_by_stem']
        groups = split_manifest.get('groups', {p.stem: p.stem for p in originals})
        if set(split_by_stem) != {p.stem for p in originals}:
            raise ValueError('Frozen original-image split does not match exported images')
    else:
        indices = list(range(len(originals)))
        random.Random(seed).shuffle(indices)
        ntrain = min(len(indices) - 1, max(1, int(len(indices) * train_ratio)))
        train_set = set(indices[:ntrain])
        split_by_stem = {p.stem: 'train' if i in train_set else 'val' for i, p in enumerate(originals)}
        groups = {p.stem: p.stem for p in originals}
    if set(split_by_stem.values()) != {'train', 'val'}:
        raise ValueError('Both train and validation originals are required')
    train_groups = {groups[k] for k,v in split_by_stem.items() if v == 'train'}
    val_groups = {groups[k] for k,v in split_by_stem.items() if v == 'val'}
    if train_groups & val_groups:
        raise ValueError('Original-image groups overlap between train and validation')
    for split in ('train', 'val'):
        for sub in ('images', 'labels'):
            (dataset_dir / sub / split).mkdir(parents=True, exist_ok=True)
    records, coverage = [], []
    stats = Counter()
    for number, original in enumerate(originals, 1):
        image = Image.open(original).convert('RGB')
        width, height = image.size
        label_path = raw_dir / 'labels' / (original.stem + '.txt')
        if not label_path.exists():
            raise ValueError(f'Missing label file: {original.name}')
        boxes = []
        for line in label_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            values = line.split()
            if len(values) != 5:
                raise ValueError(f'Expected detection xywh label: {original.name}')
            cls = int(values[0]); cx, cy, bw, bh = map(float, values[1:])
            x1, y1 = (cx-bw/2)*width, (cy-bh/2)*height
            x2, y2 = (cx+bw/2)*width, (cy+bh/2)*height
            if not all(math.isfinite(v) for v in (x1,y1,x2,y2)) or x2<=x1 or y2<=y1:
                raise ValueError(f'Invalid detection box: {original.name}')
            # Text export may round a border by a few thousandths of a pixel.
            boxes.append((cls,max(0,x1),max(0,y1),min(width,x2),min(height,y2)))
        positions = [(x,y) for y in window_positions(height,tile_size,overlap)
                     for x in window_positions(width,tile_size,overlap)]
        # Extra training windows preserve complete instances that straddle the grid.
        # Validation must match ordinary sliding inference; no label-directed windows.
        split = split_by_stem[original.stem]
        if split == 'train':
            for box in boxes:
                if not any(fully_contains(box,x,y,tile_size) for x,y in positions):
                    _,x1,y1,x2,y2 = box
                    if x2-x1<=tile_size and y2-y1<=tile_size:
                        x = min(max(0,round((x1+x2-tile_size)/2)),max(0,width-tile_size))
                        y = min(max(0,round((y1+y2-tile_size)/2)),max(0,height-tile_size))
                        if (x,y) not in positions:
                            positions.append((x,y))
        hit_counts = [0] * len(boxes)
        full_counts = [0] * len(boxes)
        for x,y in positions:
            local = [(i,clip_box(box,x,y,tile_size)) for i,box in enumerate(boxes)]
            local = [(i,b) for i,b in local if b is not None]
            name = f'{original.stem}_x{x:05d}_y{y:05d}'
            # Verified OK originals (no boxes) retain all windows. Other training
            # backgrounds use stable sampling; every validation window is retained.
            if split == 'train' and boxes and not local:
                u = int(hashlib.sha256(f'{seed}:{name}'.encode()).hexdigest()[:16],16) / 2**64
                if u >= bg_keep_ratio:
                    stats['background_tiles_skipped'] += 1
                    continue
            crop = image.crop((x,y,x+tile_size,y+tile_size))
            crop.save(dataset_dir/'images'/split/(name+'.png'),compress_level=1)
            labels = []
            for index, box in local:
                cls,x1,y1,x2,y2 = box
                labels.append(f'{cls} {(x1+x2)/2/tile_size:.9f} {(y1+y2)/2/tile_size:.9f} {(x2-x1)/tile_size:.9f} {(y2-y1)/tile_size:.9f}')
                hit_counts[index] += 1
                if fully_contains(boxes[index],x,y,tile_size):
                    full_counts[index] += 1
            (dataset_dir/'labels'/split/(name+'.txt')).write_text('\n'.join(labels)+('\n' if labels else ''),encoding='utf-8')
            records.append({'tile':name,'original_stem':original.stem,'group':groups[original.stem],'split':split,'x':x,'y':y,'annotations':len(labels)})
            stats[split] += 1
            stats[split+'_positive_tiles' if labels else split+'_background_tiles'] += 1
            stats['tile_annotations'] += len(labels)
        if any(n == 0 for n in hit_counts):
            raise ValueError(f'Dropped a source defect while tiling: {original.name}')
        if split == 'train' and any(n==0 and (b[3]-b[1]<=tile_size and b[4]-b[2]<=tile_size) for n,b in zip(full_counts,boxes)):
            raise ValueError(f'Training defect lacks a full-context window: {original.name}')
        coverage.append({'original_stem':original.stem,'split':split,'instances':len(boxes),'instances_with_tiles':sum(n>0 for n in hit_counts),'instances_fully_contained':sum(n>0 for n in full_counts)})
        stats['original_instances'] += len(boxes)
        if progress_callback:
            progress_callback(number,len(originals),f'Detection native tiles {number}/{len(originals)}')
    report = {'tile_size':tile_size,'overlap':overlap,'native_resolution':True,'split_by_stem':split_by_stem,
              'original_split_counts':dict(Counter(split_by_stem.values())),'stats':dict(stats),
              'coverage':coverage,'tiles':records}
    (dataset_dir/'tile_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'split_stats':dict(stats),'tile_manifest':str(dataset_dir/'tile_manifest.json')}
