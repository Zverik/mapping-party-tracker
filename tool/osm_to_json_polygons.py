#!/usr/bin/env python3
import argparse
import json
import sys
import logging
from math import radians, sin, cos, atan2, pi
import xml.etree.ElementTree as etree
from collections import defaultdict
from collections.abc import Generator


class Location:
    def __init__(self, lon: float, lat: float):
        self.lon = lon
        self.lat = lat

    def bearing(self, other: 'Location') -> float:
        lat1 = radians(self.lat)
        lat2 = radians(other.lat)
        dlon = radians(other.lon - self.lon)
        y = sin(dlon) * cos(lat2)
        x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
        # throws for x == 0 and y == 0
        phi = atan2(y, x)
        return (phi * 180 / pi + 360) % 360


class Polygon:
    def __init__(self, points: list[Location]):
        self.points = points

    def to_geometry(self) -> dict:
        return {
            'type': 'Polygon',
            'coordinates': [[[p.lon, p.lat] for p in self.points]],
        }

    def contains(self, point: Location) -> bool:
        return False  # TODO


class Point:
    def __init__(self, location: Location, tags: dict[str, str]):
        self.location = location
        self.tags = tags


class NextSegment:
    def __init__(self, idx: int, angle: float):
        self.idx = idx
        self.angle = angle


class Segment:
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end
        self.at_start: NextSegment | None = None
        self.at_end: NextSegment | None = None

    def other(self, pt: int) -> int:
        if pt == self.start:
            return self.end
        return self.start

    def get_next(self, pt: int) -> NextSegment:
        if pt == self.start:
            return self.at_start
        return self.at_end

    def attach(self, pt: int, nxt: NextSegment) -> None:
        if pt == self.start:
            if self.at_start is None or self.at_start.angle > nxt.angle:
                self.at_start = nxt
        else:
            if self.at_end is None or self.at_end.angle > nxt.angle:
                self.at_end = nxt


class SourceData:
    def __init__(self) -> None:
        self.segments: dict[int, Segment] = {}
        self.nodes: dict[int, Location] = {}
        self.points: list[Point] = []

    def write_osm(self, fn) -> None:
        root = etree.Element('osm', version='0.6')
        for node_id, loc in self.nodes.items():
            etree.SubElement(root, 'node', {
                'id': str(abs(node_id)),
                'version': '1',
                'lon': str(loc.lon),
                'lat': str(loc.lat),
            })
        for seg_id, seg in self.segments.items():
            way = etree.SubElement(root, 'way', {'id': str(seg_id), 'version': '1'})
            if seg.at_start:
                etree.SubElement(way, 'tag', k='start', v=f'{seg.at_start.idx} @{seg.at_start.angle}')
            if seg.at_end:
                etree.SubElement(way, 'tag', k='end', v=f'{seg.at_end.idx} @{seg.at_end.angle}')
            etree.SubElement(way, 'nd', ref=str(abs(seg.start)))
            etree.SubElement(way, 'nd', ref=str(abs(seg.end)))
        tree = etree.ElementTree(root)
        tree.write(fn, 'utf-8')

    def remove_duplicates(self) -> None:
        seen = set[tuple[int, int]]()
        removing: list[int] = []
        for idx, seg in self.segments.items():
            k = (seg.start, seg.end)
            if k in seen:
                removing.append(idx)
            else:
                seen.add(k)
                seen.add((seg.end, seg.start))
        for idx in removing:
            del self.segments[idx]

    def remove_loose_ends(self) -> None:
        refs = defaultdict[int, list[int]](list)
        for idx, s in self.segments.items():
            refs[s.start].append(idx)
            refs[s.end].append(idx)
        while True:
            removing = set[int]()
            for n, segs in refs.items():
                if len(segs) == 1:
                    removing.add(segs[0])
            if not removing:
                break
            for seg_id in removing:
                seg = self.segments.pop(seg_id)
                refs[seg.start].remove(seg_id)
                refs[seg.end].remove(seg_id)

    def angle(self, n1: int, n2: int, n3: int) -> float:
        b1 = self.nodes[n1].bearing(self.nodes[n2])
        b2 = self.nodes[n2].bearing(self.nodes[n3])
        return (b1 + 180 - b2 + 360) % 360

    def link_segments(self) -> None:
        refs = defaultdict[int, list[int]](list)
        for idx, s in self.segments.items():
            refs[s.start].append(idx)
            refs[s.end].append(idx)
        for node, segments in refs.items():
            # Node has N segments attached to it. Find smallest angles for both ends.
            for seg_id in segments:
                segment = self.segments[seg_id]
                for seg_id2 in segments:
                    if seg_id2 != seg_id:
                        seg2 = self.segments[seg_id2]
                        angle = self.angle(segment.other(node), node, seg2.other(node))
                        segment.attach(node, NextSegment(seg_id2, angle))

    def find_polygons(self) -> Generator[Polygon]:
        queue = set[tuple[int, bool]]()
        # True means start to end, False means end to start.
        for k in self.segments:
            queue.add((k, True))
            queue.add((k, False))

        while queue:
            start = queue.pop()
            logging.debug(f'Used {start}')
            seg = self.segments[start[0]]
            polygon = [seg.start, seg.end]
            if not start[1]:
                polygon.reverse()

            sum_angles = 0.0
            seg_ids = [start[0]]
            safeguard = 1000
            while True:
                last = polygon[-1]
                nxt = seg.get_next(last)
                sum_angles += nxt.angle
                seg_ids.append(nxt.idx)
                seg = self.segments[nxt.idx]
                logging.debug(f'Used {(nxt.idx, seg.start == last)}')
                queue.remove((nxt.idx, seg.start == last))

                last = seg.other(last)
                polygon.append(last)
                if last == polygon[0]:
                    nxt = seg.get_next(last)
                    if nxt.idx != seg_ids[0]:
                        logging.debug(f'Warning: next segment is {nxt.idx}, not {seg_ids[0]}')
                    sum_angles += nxt.angle
                    break
                safeguard -= 1
                if safeguard == 0:
                    raise Exception('Could not close a loop')

            logging.debug(f'Found polygon of segments {seg_ids} with angle sum {round(sum_angles)}')
            if round(sum_angles) != 180 * (len(seg_ids) - 2):
                logging.debug('Skipping')
            else:
                yield Polygon([self.nodes[n] for n in polygon])

    def build_properties(self, polygon: Polygon) -> dict[str, str]:
        tags = [p.tags for p in self.points if polygon.contains(p.location)]
        if not tags:
            return {}
        result = tags[0]
        for i in range(1, len(tags)):
            for k, v in tags[i].items():
                if k not in result:
                    result[k] = v
                else:
                    result[k] = f'{result[k]},{v}'
        return result


def read_osm(fn: str) -> SourceData:
    data = SourceData()
    nodes: dict[int, Point] = {}
    last_seg = 0
    for _, elem in etree.iterparse(fn, ['end']):
        if elem.tag == 'way':
            nds = [int(nd.get('ref')) for nd in elem.findall('nd')]
            for i in range(1, len(nds)):
                last_seg += 1
                if nds[i-1] != nds[i]:
                    data.segments[last_seg] = Segment(nds[i-1], nds[i])
        elif elem.tag == 'node':
            tags = {t.get('k'): t.get('v') for t in elem.findall('tag')}
            nodes[int(elem.get('id'))] = Point(
                Location(float(elem.get('lon')), float(elem.get('lat'))), tags)

    data.segments = {idx: s for idx, s in data.segments.items()
                     if s.start in nodes and s.end in nodes}
    referenced = (set(s.start for s in data.segments.values()) |
                  set(s.end for s in data.segments.values()))
    data.nodes = {idx: n.location for idx, n in nodes.items()
                  if idx in referenced}
    data.points = [n for idx, n in nodes.items()
                   if n.tags and idx not in referenced]
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Converts ways in OSM file to polygons in GeoJSON. '
        'Put tagged nodes in the centers of polygons to tag enclosing '
        'polygons.')
    parser.add_argument('osm', type=argparse.FileType('r'),
                        help='Source OSM file')
    parser.add_argument('-o', '--json', type=argparse.FileType('w'),
                        help='Output file, stdout by default')
    parser.add_argument('--dump', type=argparse.FileType('w'),
                        help='Dump intermediate data into an OSM file')
    parser.add_argument('-v', action='store_true',
                        help='Display some technical info')
    options = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if not options.v else logging.DEBUG,
        format='%(message)s')
    data = read_osm(options.osm)
    data.remove_duplicates()
    data.remove_loose_ends()
    data.link_segments()
    if options.dump:
        data.write_osm(options.dump)

    features: list[dict] = []
    for polygon in data.find_polygons():
        features.append({
            'type': 'Feature',
            'properties': data.build_properties(polygon),
            'geometry': polygon.to_geometry(),
        })
    w = options.json or sys.stdout
    json.dump({'type': 'FeatureCollection', 'features': features}, w)
