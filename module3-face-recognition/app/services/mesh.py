"""Cache static graph validation ONLY; a fresh closed graph for every image.

The pinned MediaPipe CalculatorGraph API accepts a ValidatedGraphConfig. It
contains topology/options, not input packets or user outputs. Reusing that
immutable description avoids Python graph-interface setup on each request.
"""

from functools import lru_cache

import mediapipe as mp
from mediapipe.python._framework_bindings import validated_graph_config


@lru_cache(maxsize=1)
def validated_config():
    # No image is ever submitted to this temporary configuration template.
    template = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                             refine_landmarks=False, min_detection_confidence=.5)
    try:
        config = validated_graph_config.ValidatedGraphConfig()
        config.initialize(graph_config=template._graph.text_config)
        return config
    finally:
        template.close()


def landmarks_for_image(image):
    graph = mp.CalculatorGraph(validated_graph_config=validated_config())
    result = []

    def observe(_stream, packet):
        if not packet.is_empty():
            result.extend(mp.packet_getter.get_proto_list(packet))

    try:
        graph.observe_output_stream("multi_face_landmarks", observe, True)
        graph.start_run({"num_faces": mp.packet_creator.create_int(1),
                         "with_attention": mp.packet_creator.create_bool(False),
                         "use_prev_landmarks": mp.packet_creator.create_bool(False)})
        frame = mp.packet_creator.create_image_frame(image_format=mp.ImageFormat.SRGB, data=image)
        graph.add_packet_to_input_stream("image", frame.at(33333))
        graph.wait_until_idle()
        return result
    finally:
        graph.close()
