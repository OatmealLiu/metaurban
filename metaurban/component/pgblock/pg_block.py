import copy
from metaurban.constants import MetaUrbanType
from metaurban.engine.logger import get_logger
import logging
from collections import OrderedDict
from typing import Union, List

import numpy as np

from metaurban.component.block.base_block import BaseBlock
from metaurban.component.road_network import Road
from metaurban.component.road_network.node_road_network import NodeRoadNetwork
from metaurban.constants import PGDrivableAreaProperty
from metaurban.constants import PGLineType
import numpy as np
import random
logger = get_logger()


class PGBlockSocket:
    """
    A pair of roads in reverse direction
    Positive_road is right road, and Negative road is left road on which cars drive in reverse direction
    BlockSocket is a part of block used to connect other blocks
    """
    def __init__(self, positive_road: Road, negative_road: Road = None):
        self.positive_road = positive_road
        self.negative_road = negative_road if negative_road else None
        self.index = None

    def set_index(self, block_name: str, index: int):
        self.index = self.get_real_index(block_name, index)

    @classmethod
    def get_real_index(cls, block_name: str, index: int):
        return "{}-socket{}".format(block_name, index)

    def is_socket_node(self, road_node):
        if road_node == self.positive_road.start_node or road_node == self.positive_road.end_node or \
                road_node == self.negative_road.start_node or road_node == self.negative_road.end_node:
            return True
        else:
            return False

    def get_socket_in_reverse(self):
        """
        Return a new socket whose positive road=self.negative_road, negative_road=self.positive_road
        """
        new_socket = copy.deepcopy(self)
        new_socket.positive_road, new_socket.negative_road = self.negative_road, self.positive_road
        return new_socket

    def is_same_socket(self, other):
        return True if self.positive_road == other.positive_road and self.negative_road == other.negative_road else False

    def get_positive_lanes(self, global_network):
        return self.positive_road.get_lanes(global_network)

    def get_negative_lanes(self, global_network):
        return self.negative_road.get_lanes(global_network)


class PGBlock(BaseBlock):
    """
    Abstract class of Block,
    BlockSocket: a part of previous block connecting this block

    <----------------------------------------------
    road_2_end <---------------------- road_2_start
    <~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~>
    road_1_start ----------------------> road_1_end
    ---------------------------------------------->
    BlockSocket = tuple(road_1, road_2)

    When single-direction block created, road_2 in block socket is useless.
    But it's helpful when a town is created.
    """
    def __init__(
        self,
        block_index: int,
        pre_block_socket: PGBlockSocket,
        global_network: NodeRoadNetwork,
        random_seed,
        ignore_intersection_checking=False,
        remove_negative_lanes=False,
        side_lane_line_type=None,
        center_line_type=None,
        # crswalk_density=0.5,
    ):
        self.crswalk_density = self.engine.global_config["crswalk_density"]
        # print("---- crswalk_density: ----", self.crswalk_density)

        if self.ID == 'X' or self.ID == 'O' or self.ID == 'T':
            self.valid_crswalk = random.sample([1, 2, 3, 4, 5, 6], round(self.crswalk_density * 6))
        # elif self.ID == 'T':
        #     self.valid_crswalk = random.sample([3,4,5,6], round(self.crswalk_density * 4))
        elif self.ID == 'C':
            self.valid_crswalk = random.sample([1, 2, 3], round(self.crswalk_density * 3))
        # else: self.valid_crswalk = []
        # print('!!!!crswalk_density: ', self.ID, self.valid_crswalk)

        # Specify the lane line type
        self.side_lane_line_type = side_lane_line_type
        self.center_line_type = center_line_type

        self.name = str(block_index) + self.ID
        super(PGBlock, self).__init__(
            block_index,
            global_network,
            random_seed,
            ignore_intersection_checking=ignore_intersection_checking,
        )
        # block information
        assert self.SOCKET_NUM is not None, "The number of Socket should be specified when define a new block"
        if block_index == 0:
            from metaurban.component.pgblock.first_block import FirstPGBlock
            assert isinstance(self, FirstPGBlock), "only first block can use block index 0"
        elif block_index < 0:
            logging.debug("It is recommended that block index should > 1")
        self.number_of_sample_trial = 0

        # own sockets, one block derives from a socket, but will have more sockets to connect other blocks
        self._sockets = OrderedDict()

        # used to connect previous blocks, save its info here
        self.pre_block_socket = pre_block_socket
        self.pre_block_socket_index = pre_block_socket.index

        # used to create this block, but for first block it is nonsense
        self.remove_negative_lanes = remove_negative_lanes
        if block_index != 0:
            self.positive_lanes = self.pre_block_socket.get_positive_lanes(self._global_network)
            self.positive_lane_num = len(self.positive_lanes)
            self.positive_basic_lane = self.positive_lanes[-1]  # most right or outside lane is the basic lane
            self.lane_width = self.positive_basic_lane.width_at(0)
            if not remove_negative_lanes:
                self.negative_lanes = self.pre_block_socket.get_negative_lanes(self._global_network)
                self.negative_lane_num = len(self.negative_lanes)
                self.negative_basic_lane = self.negative_lanes[-1]  # most right or outside lane is the basic lane

        # random sample sidewalk type
        if 'predefined_config' in self.engine.global_config:
            self.engine.global_config['sidewalk_type'] = self.engine.global_config['predefined_config']['Sidewalk'][0][
                'Type']
        self.sidewalk_type = self.engine.global_config['sidewalk_type']

        seed = self.engine.global_random_seed
        import os
        import torch
        random.seed(seed)
        os.environ['PYTHONHASHSEED'] = str(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

        if 'predefined_config' in self.engine.global_config:
            if self.sidewalk_type == 'Narrow Sidewalk':
                self.near_road_width = None
                self.near_road_buffer_width = self.engine.global_config['predefined_config']['Sidewalk'][1][
                    'Buffer_Lane_Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][1]['Buffer_Lane_Furnishing_Width'][1]
                        -
                        self.engine.global_config['predefined_config']['Sidewalk'][1]['Buffer_Lane_Furnishing_Width'][0]
                    )
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_buffer_width *= 2
                self.main_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Narrow Sidewalk with Trees':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = None
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Ribbon Sidewalk':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = None
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][0]
                    )
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.far_from_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Neighborhood 1':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = self.engine.global_config['predefined_config']['Sidewalk'][1][
                    'Buffer_Lane_Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][1]['Buffer_Lane_Furnishing_Width'][1]
                        -
                        self.engine.global_config['predefined_config']['Sidewalk'][1]['Buffer_Lane_Furnishing_Width'][0]
                    )
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.near_road_buffer_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Neighborhood 2':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = None
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][0]
                    )
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.far_from_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Medium Commercial':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = None
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = None
                self.far_from_width = self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][0]
                    )
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.far_from_width *= 2
                self.valid_house_width *= 2
            elif self.sidewalk_type == 'Wide Commercial':
                self.near_road_width = self.engine.global_config['predefined_config']['Sidewalk'][2][
                    'Furnishing_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][2]['Furnishing_Width'][0]
                    )
                self.near_road_buffer_width = None
                self.main_width = self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][3]['Clear_Width'][0]
                    )
                self.far_from_buffer_width = self.engine.global_config['predefined_config']['Sidewalk'][4][
                    'Buffer_Frontage_Clear_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][4]['Buffer_Frontage_Clear_Width'][1]
                        -
                        self.engine.global_config['predefined_config']['Sidewalk'][4]['Buffer_Frontage_Clear_Width'][0]
                    )
                self.far_from_width = self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][
                    0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][5]['Frontage_Width'][0]
                    )
                self.valid_house_width = self.engine.global_config['predefined_config']['Sidewalk'][6][
                    'Building_Width'][0] + np.random.uniform(0, 1) * (
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][1] -
                        self.engine.global_config['predefined_config']['Sidewalk'][6]['Building_Width'][0]
                    )
                self.near_road_width *= 2
                self.main_width *= 2
                self.far_from_buffer_width *= 2
                self.far_from_width *= 2
                self.valid_house_width *= 2
            else:
                raise NotImplementedError
        else:
            if self.sidewalk_type == 'Narrow Sidewalk':
                self.near_road_width = None
                self.near_road_buffer_width = PGDrivableAreaProperty.NARROW_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NARROW_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.NARROW_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.main_width = PGDrivableAreaProperty.NARROW_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(0, 1) * (
                    PGDrivableAreaProperty.NARROW_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.NARROW_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Narrow Sidewalk with Trees':
                self.near_road_width = PGDrivableAreaProperty.NARROWT_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NARROWT_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.NARROWT_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = None
                self.main_width = PGDrivableAreaProperty.NARROWT_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(0, 1) * (
                    PGDrivableAreaProperty.NARROWT_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.NARROWT_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Ribbon Sidewalk':
                self.near_road_width = PGDrivableAreaProperty.RIBBON_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = None
                self.main_width = PGDrivableAreaProperty.RIBBON_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(0, 1) * (
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = PGDrivableAreaProperty.RIBBON_SIDEWALK_FAR_MIN_WIDTH + np.random.uniform(0, 1) * (
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_FAR_MAX_WIDTH -
                    PGDrivableAreaProperty.RIBBON_SIDEWALK_FAR_MIN_WIDTH
                )
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Neighborhood 1':
                self.near_road_width = PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_BUFFER_NEAR_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_BUFFER_NEAR_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_BUFFER_NEAR_MIN_WIDTH
                )
                self.main_width = PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = None
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Neighborhood 2':
                self.near_road_width = PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = None
                self.main_width = PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_BUFFER_FAR_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_BUFFER_FAR_MAX_WIDTH -
                    PGDrivableAreaProperty.NEIGHBORHOOD2_SIDEWALK_BUFFER_FAR_MIN_WIDTH
                )
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Medium Commercial':
                self.near_road_width = PGDrivableAreaProperty.MediumCommercial_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = None
                self.main_width = PGDrivableAreaProperty.MediumCommercial_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = None
                self.far_from_width = PGDrivableAreaProperty.MediumCommercial_SIDEWALK_FAR_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_FAR_MAX_WIDTH -
                    PGDrivableAreaProperty.MediumCommercial_SIDEWALK_FAR_MIN_WIDTH
                )
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            elif self.sidewalk_type == 'Wide Commercial':
                self.near_road_width = PGDrivableAreaProperty.WideCommercial_SIDEWALK_NEAR_ROAD_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_NEAR_ROAD_MAX_WIDTH -
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_NEAR_ROAD_MIN_WIDTH
                )
                self.near_road_buffer_width = None
                self.main_width = PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_MAX_WIDTH -
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_MIN_WIDTH
                )
                self.far_from_buffer_width = PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_BUFFER_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_BUFFER_MAX_WIDTH -
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_MAIN_BUFFER_MIN_WIDTH
                )
                self.far_from_width = PGDrivableAreaProperty.WideCommercial_SIDEWALK_FAR_MIN_WIDTH + np.random.uniform(
                    0, 1
                ) * (
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_FAR_MAX_WIDTH -
                    PGDrivableAreaProperty.WideCommercial_SIDEWALK_FAR_MIN_WIDTH
                )
                self.valid_house_width = PGDrivableAreaProperty.HOUSE_WIDTH
            else:
                raise NotImplementedError
        if 'test_terrain_system' not in self.engine.global_config:
            self.engine.global_config['test_terrain_system'] = False
        if 'test_slope_system' not in self.engine.global_config:
            self.engine.global_config['test_slope_system'] = False
        if 'test_rough_system' not in self.engine.global_config:
            self.engine.global_config['test_rough_system'] = False
        if self.engine.global_config['test_terrain_system']:
            print('Using terrain system')
            self.near_road_buffer_width = 10.
            self.near_road_width = 10.
            self.main_width = 10.
            self.far_from_buffer_width = 10.
            self.far_from_width = 10.
            self.valid_house_width = 10.
        elif self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            print('Using slope system')
            self.near_road_buffer_width = 5.
            self.near_road_width = 5.
            self.main_width = 5.
            self.far_from_buffer_width = 5.
            self.far_from_width = 5.
            self.valid_house_width = 5.
            self.slo_nb = []
            self.slo_n = []
            self.slo_s = []
            self.slo_fb = []
            self.slo_f = []
            self.slo_h = []
        elif self.engine.global_config['test_rough_system']:
            print('Using slope system')
            self.near_road_buffer_width = 5.
            self.near_road_width = 5.
            self.main_width = 5.
            self.far_from_buffer_width = 5.
            self.far_from_width = 5.
            self.valid_house_width = 5.
            self.slo_nb = []
            self.slo_n = []
            self.slo_s = []
            self.slo_fb = []
            self.slo_f = []
            self.slo_h = []

    def _sample_topology(self) -> bool:
        """
        Sample a new topology, clear the previous settings at first
        """
        self.number_of_sample_trial += 1
        no_cross = self._try_plug_into_previous_block()
        return no_cross

    def get_socket(self, index: Union[str, int]) -> PGBlockSocket:
        if isinstance(index, int):
            if index < 0 or index >= len(self._sockets):
                raise ValueError("Socket of {}: index out of range {}".format(self.class_name, len(self._sockets)))
            socket_index = list(self._sockets)[index]
        else:
            assert index.startswith(self.name)
            socket_index = index
        assert socket_index in self._sockets, (socket_index, self._sockets.keys())
        return self._sockets[socket_index]

    def add_respawn_roads(self, respawn_roads: Union[List[Road], Road]):
        """
        Use this to add spawn roads instead of modifying the list directly
        """
        if isinstance(respawn_roads, List):
            for road in respawn_roads:
                self._add_one_respawn_road(road)
        elif isinstance(respawn_roads, Road):
            self._add_one_respawn_road(respawn_roads)
        else:
            raise ValueError("Only accept List[Road] or Road in this func")

    def add_sockets(self, sockets: Union[List[PGBlockSocket], PGBlockSocket]):
        """
        Use this to add sockets instead of modifying the list directly
        """
        if isinstance(sockets, PGBlockSocket):
            self._add_one_socket(sockets)
        elif isinstance(sockets, List):
            for socket in sockets:
                self._add_one_socket(socket)

    def _add_one_socket(self, socket: PGBlockSocket):
        assert isinstance(socket, PGBlockSocket), "Socket list only accept BlockSocket Type"
        if socket.index is not None and not socket.index.startswith(self.name):
            logging.warning(
                "The adding socket has index {}, which is not started with this block name {}. This is dangerous! "
                "Current block has sockets: {}.".format(socket.index, self.name, self.get_socket_indices())
            )
        if socket.index is None:
            # if this socket is self block socket
            socket.set_index(self.name, len(self._sockets))
        self._sockets[socket.index] = socket

    def _clear_topology(self):
        super(PGBlock, self)._clear_topology()
        self._sockets.clear()

    def _try_plug_into_previous_block(self) -> bool:
        """
        Try to plug this Block to previous block's socket, return True for success, False for road cross
        """
        raise NotImplementedError

    @staticmethod
    def create_socket_from_positive_road(road: Road) -> PGBlockSocket:
        """
        We usually create road from positive road, thus this func can get socket easily.
        Note: it is not recommended to generate socket from negative road
        """
        assert road.start_node[0] != Road.NEGATIVE_DIR and road.end_node[0] != Road.NEGATIVE_DIR, \
            "Socket can only be created from positive road"
        positive_road = Road(road.start_node, road.end_node)
        return PGBlockSocket(positive_road, -positive_road)

    def get_socket_indices(self):
        ret = list(self._sockets.keys())
        for r in ret:
            assert isinstance(r, str)
        return ret

    def get_socket_list(self):
        return list(self._sockets.values())

    def set_part_idx(self, x):
        """
        It is necessary to divide block to some parts in complex block and give them unique id according to part idx
        """
        self.PART_IDX = x
        self.ROAD_IDX = 0  # clear the road idx when create new part

    def add_road_node(self):
        """
        Call me to get a new node name of this block.
        It is more accurate and recommended to use road_node() to get a node name
        """
        self.ROAD_IDX += 1
        return self.road_node(self.PART_IDX, self.ROAD_IDX - 1)

    def road_node(self, part_idx: int, road_idx: int) -> str:
        """
        return standard road node name
        """
        return self.node(self.block_index, part_idx, road_idx)

    @classmethod
    def node(cls, block_idx: int, part_idx: int, road_idx: int) -> str:  #1C0_0_
        return str(block_idx) + cls.ID + str(part_idx) + cls.DASH + str(road_idx) + cls.DASH

    def get_intermediate_spawn_lanes(self):
        trigger_lanes = self.block_network.get_positive_lanes()
        respawn_lanes = self.get_respawn_lanes()
        for lanes in respawn_lanes:
            if lanes not in trigger_lanes:
                trigger_lanes.append(lanes)
        return trigger_lanes

    @property
    def block_network_type(self):
        return NodeRoadNetwork

    def create_in_world(self):  # panda3d # called everytime when construct a new block
        graph = self.block_network.graph
        for _from, to_dict in graph.items():
            for _to, lanes in to_dict.items():
                for _id, lane in enumerate(lanes):

                    self._construct_lane(lane, (_from, _to, _id))
                    choose_side = [True, True] if _id == len(lanes) - 1 else [True, False]
                    choose_side = [True, True]
                    if Road(_from, _to).is_negative_road() and _id == 0:
                        # draw center line with positive road
                        choose_side = [False, False]
                    self._construct_lane_line_in_block(lane, choose_side)

        self._construct_nearroadsidewalk()
        self._construct_sidewalk()
        self._construct_farfromroadsidewalk()
        self._construct_nearroadsidewalk_buffer()
        self._construct_farfromroadsidewalk_buffer()
        self._construct_valid_region()

        self._construct_crosswalk()
        # print("Return. finished building one block.")

    #### TODO
    def _construct_broken_line(self, lane, lateral, line_color, line_type):
        """
        Lateral: left[-1/2 * width] or right[1/2 * width]
        """
        segment_num = int(lane.length / (2 * PGDrivableAreaProperty.STRIPE_LENGTH))
        for segment in range(segment_num):
            start = lane.position(segment * PGDrivableAreaProperty.STRIPE_LENGTH * 2, lateral)
            end = lane.position(
                segment * PGDrivableAreaProperty.STRIPE_LENGTH * 2 + PGDrivableAreaProperty.STRIPE_LENGTH, lateral
            )
            if segment == segment_num - 1:
                end = lane.position(lane.length - PGDrivableAreaProperty.STRIPE_LENGTH, lateral)
            node_path_list = self._construct_lane_line_segment(start, end, line_color, line_type)
            self._node_path_list.extend(node_path_list)

        # assert MetaUrbanType.is_broken_line(line_type)
        # points = lane.get_polyline(2, lateral)
        # for index in range(0, len(points) - 1, 2):
        #     if index + 1 < len(points):
        #         node_path_list = self._construct_lane_line_segment(
        #             points[index], points[index + 1], line_color, line_type
        #         )
        #         self._node_path_list.extend(node_path_list)

    def _construct_continuous_line(self, lane, lateral, line_color, line_type):
        """
        We process straight line to several pieces by default, which can be optimized through overriding this function
        Lateral: left[-1/2 * width] or right[1/2 * width]
        """
        segment_num = int(lane.length / PGDrivableAreaProperty.LANE_SEGMENT_LENGTH)
        if segment_num == 0:
            start = lane.position(0, lateral)
            end = lane.position(lane.length, lateral)
            node_path_list = self._construct_lane_line_segment(start, end, line_color, line_type)
            self._node_path_list.extend(node_path_list)
        for segment in range(segment_num):
            start = lane.position(PGDrivableAreaProperty.LANE_SEGMENT_LENGTH * segment, lateral)
            if segment == segment_num - 1:
                end = lane.position(lane.length, lateral)
            else:
                end = lane.position((segment + 1) * PGDrivableAreaProperty.LANE_SEGMENT_LENGTH, lateral)
            node_path_list = self._construct_lane_line_segment(start, end, line_color, line_type)
            self._node_path_list.extend(node_path_list)

    def _generate_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        """
        Construct the sidewalk for this lane
        Args:
            block:

        Returns:

        """
        if str(lane.index) in self.sidewalks:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        if self.near_road_buffer_width is not None:
            start_lat = start_lat + self.near_road_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.near_road_width is not None:
            start_lat = start_lat + self.near_road_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        side_lat = start_lat + self.main_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        if lane.radius != 0 and side_lat > lane.radius:
            logger.warning(
                "The sidewalk width ({}) is too large."
                " It should be < radius ({})".format(side_lat, lane.radius)
            )
            return
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.sidewalks[f"SDW_{self.ID}_" + str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_s.append(polygon)

    def build_crosswalk_block(self, key, lane, sidewalk_height, lateral_direction, longs, start_lat, side_lat):
        polygon = []
        assert lateral_direction == -1 or lateral_direction == 1

        start_lat *= lateral_direction
        side_lat *= lateral_direction

        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        # print(f'{key}={polygon}')

        self.crosswalks[key] = {
            # self.sidewalks[str(lane.index)] = {
            "type": MetaUrbanType.CROSSWALK,  #BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }

    def _generate_nearroad_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        assert self.near_road_width is not None

        if str(lane.index) in self.sidewalks_near_road:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        if self.near_road_buffer_width is not None:
            start_lat = start_lat + self.near_road_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        side_lat = start_lat + self.near_road_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.sidewalks_near_road[str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_n.append(polygon)

    def _generate_farfrom_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        assert self.far_from_width is not None

        if str(lane.index) in self.sidewalks_farfrom_road:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        if self.near_road_buffer_width is not None:
            start_lat = start_lat + self.near_road_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.near_road_width is not None:
            start_lat = start_lat + self.near_road_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.main_width is not None:
            start_lat = start_lat + self.main_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.far_from_buffer_width is not None:
            start_lat = start_lat + self.far_from_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        side_lat = start_lat + self.far_from_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.sidewalks_farfrom_road[str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_f.append(polygon)

    def _generate_nearroad_buffer_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        assert self.near_road_buffer_width is not None

        if str(lane.index) in self.sidewalks_near_road_buffer:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        side_lat = start_lat + self.near_road_buffer_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.sidewalks_near_road_buffer[str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_nb.append(polygon)

    def _generate_farfromroad_buffer_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        assert self.far_from_buffer_width is not None

        if str(lane.index) in self.sidewalks_farfrom_road_buffer:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        if self.near_road_buffer_width is not None:
            start_lat = start_lat + self.near_road_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.near_road_width is not None:
            start_lat = start_lat + self.near_road_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.main_width is not None:
            start_lat = start_lat + self.main_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        side_lat = start_lat + self.far_from_buffer_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.sidewalks_farfrom_road_buffer[str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_fb.append(polygon)

    def _generate_valid_region_sidewalk_from_line(self, lane, sidewalk_height=None, lateral_direction=1):
        assert self.valid_house_width is not None

        if str(lane.index) in self.valid_region:
            logger.warning("Sidewalk id {} already exists!".format(str(lane.index)))
            return
        polygon = []
        longs = np.arange(
            0, lane.length + PGDrivableAreaProperty.SIDEWALK_LENGTH, PGDrivableAreaProperty.SIDEWALK_LENGTH
        )
        start_lat = +lane.width_at(0) / 2
        if self.near_road_buffer_width is not None:
            start_lat = start_lat + self.near_road_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.near_road_width is not None:
            start_lat = start_lat + self.near_road_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.main_width is not None:
            start_lat = start_lat + self.main_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.far_from_buffer_width is not None:
            start_lat = start_lat + self.far_from_buffer_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        if self.far_from_width is not None:
            start_lat = start_lat + self.far_from_width + 6. * (
                (self.engine.global_config['test_slope_system'] + self.engine.global_config['test_rough_system']) > 0
            )
        side_lat = start_lat + self.valid_house_width
        assert lateral_direction == -1 or lateral_direction == 1
        start_lat *= lateral_direction
        side_lat *= lateral_direction
        for k, lateral in enumerate([start_lat, side_lat]):
            if k == 1:
                longs = longs[::-1]
            for longitude in longs:
                longitude = min(lane.length + 0.1, longitude)
                point = lane.position(longitude, lateral)
                polygon.append([point[0], point[1]])
        self.valid_region[str(lane.index)] = {
            "type": MetaUrbanType.BOUNDARY_SIDEWALK,
            "polygon": polygon,
            "height": sidewalk_height
        }
        if self.engine.global_config['test_slope_system'] or self.engine.global_config['test_rough_system']:
            polygon = []
            for k, lateral in enumerate([side_lat + (i + 1) * 0.03 for i in range(200)]):
                if k == 1:
                    longs = longs[::-1]
                for longitude in longs:
                    longitude = min(lane.length + 0.1, longitude)
                    point = lane.position(longitude, lateral)
                    polygon.append([point[0], point[1]])
            self.slo_h.append(polygon)

    def _construct_lane_line_in_block(self, lane, construct_left_right=(True, True)):
        """
        Construct lane line in the Panda3d world for getting contact information
        """
        for idx, line_type, line_color, need, in zip([-1, 1], lane.line_types, lane.line_colors, construct_left_right):
            # print(need)
            if not need:
                continue
            lateral = idx * lane.width_at(0) / 2
            # print(lateral)
            if line_type == PGLineType.CONTINUOUS:
                self._construct_continuous_line(lane, lateral, line_color, line_type)
            elif line_type == PGLineType.BROKEN:
                self._construct_broken_line(lane, lateral, line_color, line_type)
                try:
                    self._generate_crosswalk_from_line(lane)
                except:
                    pass
            elif line_type == PGLineType.SIDE:
                self._construct_continuous_line(lane, lateral, line_color, line_type)
                if self.engine.global_config['test_terrain_system'] or self.engine.global_config[
                        'test_slope_system'] or self.engine.global_config['test_rough_system']:
                    self._generate_nearroad_buffer_sidewalk_from_line(lane, lateral_direction=idx)
                    self._generate_nearroad_sidewalk_from_line(lane, lateral_direction=idx)
                    self._generate_sidewalk_from_line(lane, lateral_direction=idx)
                    self._generate_farfromroad_buffer_sidewalk_from_line(lane, lateral_direction=idx)
                    self._generate_farfrom_sidewalk_from_line(lane, lateral_direction=idx)
                    self._generate_valid_region_sidewalk_from_line(lane, lateral_direction=idx)
                elif self.sidewalk_type == 'Narrow Sidewalk':
                    self._generate_nearroad_buffer_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Narrow Sidewalk with Trees':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Ribbon Sidewalk':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_farfrom_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Neighborhood 1':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_nearroad_buffer_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Neighborhood 2':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_farfrom_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Medium Commercial':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_farfrom_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                elif self.sidewalk_type == 'Wide Commercial':
                    self._generate_nearroad_sidewalk_from_line(lane)
                    self._generate_sidewalk_from_line(lane)
                    self._generate_farfromroad_buffer_sidewalk_from_line(lane)
                    self._generate_farfrom_sidewalk_from_line(lane)
                    self._generate_valid_region_sidewalk_from_line(lane)
                else:
                    raise NotImplementedError

            elif line_type == PGLineType.GUARDRAIL:
                self._construct_continuous_line(lane, lateral, line_color, line_type)
                if self.engine.global_config['test_terrain_system'] or self.engine.global_config[
                        'test_slope_system'] or self.engine.global_config['test_rough_system']:
                    self._generate_nearroad_buffer_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfromroad_buffer_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfrom_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )

                elif self.sidewalk_type == 'Narrow Sidewalk':
                    self._generate_nearroad_buffer_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Narrow Sidewalk with Trees':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Ribbon Sidewalk':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfrom_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Neighborhood 1':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_nearroad_buffer_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Neighborhood 2':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfrom_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Medium Commercial':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfrom_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                elif self.sidewalk_type == 'Wide Commercial':
                    self._generate_nearroad_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfromroad_buffer_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_farfrom_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                    self._generate_valid_region_sidewalk_from_line(
                        lane, sidewalk_height=PGDrivableAreaProperty.GUARDRAIL_HEIGHT, lateral_direction=idx
                    )
                else:
                    raise NotImplementedError

            elif line_type == PGLineType.NONE:
                continue
            else:
                raise ValueError(
                    "You have to modify this function and implement a constructing method for line type: {}".
                    format(line_type)
                )
