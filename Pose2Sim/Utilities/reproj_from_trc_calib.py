#!/usr/bin/env python
# -*- coding: utf-8 -*-


'''
    ##################################################
    ## Reproject 3D points on camera planes         ##
    ##################################################
    
    Reproject 3D points from a trc file to the camera planes determined by a 
    toml calibration file.

    The output 2D points can be chosen to follow the DeepLabCut (default) or 
    the OpenPose format. If OpenPose is chosen, the BODY_25B model is used, 
    with ear and eye at coordinates (0,0) since they are not used by Pose2Sim. 
    You can change the BODY_25B tree if you need to reproject in OpenPose 
    format with a different model.
    
    Usage: 
    from Pose2Sim.Utilities import reproj_from_trc_calib; reproj_from_trc_calib.reproj_from_trc_calib_func(r'<input_trc_file>', r'<input_calib_file>', r'<openpose_or_deeplabcut_format>', r'<output_file>')
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file -f 'openpose'
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file -f 'deeplabcut' -o output_file
'''


## INIT
import os
import pandas as pd
import numpy as np
import toml
import cv2
import json
from anytree import Node, RenderTree
from copy import deepcopy
import argparse


## AUTHORSHIP INFORMATION
__author__ = "David Pagnon"
__copyright__ = "Copyright 2021, Pose2Sim"
__credits__ = ["David Pagnon"]
__license__ = "BSD 3-Clause License"
__version__ = "0.5"
__maintainer__ = "David Pagnon"
__email__ = "contact@david-pagnon.com"
__status__ = "Development"


## SKELETON
'''BODY_25B (full-body without hands, experimental, from OpenPose)
https://github.com/CMU-Perceptual-Computing-Lab/openpose_train/blob/master/experimental_models/README.md
Adjust it if your want to reproject in OpenPose format with a different model'''
nb_joints = 25
BODY_25B = Node("CHip", id=None, children=[
    Node("RHip", id=12, children=[
        Node("RKnee", id=14, children=[
            Node("RAnkle", id=16, children=[
                Node("RBigToe", id=22, children=[
                    Node("RSmallToe", id=23),
                ]),
                Node("RHeel", id=24),
            ]),
        ]),
    ]),
    Node("LHip", id=11, children=[
        Node("LKnee", id=13, children=[
            Node("LAnkle", id=15, children=[
                Node("LBigToe", id=19, children=[
                    Node("LSmallToe", id=20),
                ]),
                Node("LHeel", id=21),
            ]),
        ]),
    ]),
    Node("Neck", id=17, children=[
        Node("Head", id=18, children=[
            Node("Nose", id=0),
        ]),
        Node("RShoulder", id=6, children=[
            Node("RElbow", id=8, children=[
                Node("RWrist", id=10),
            ]),
        ]),
        Node("LShoulder", id=5, children=[
            Node("LElbow", id=7, children=[
                Node("LWrist", id=9),
            ]),
        ]),
    ]),
])


## FUNCTIONS
def computeP(calib_file):
    '''
    Compute projection matrices from toml calibration file.
    
    INPUT:
    - calib_file: calibration .toml file.
    
    OUTPUT:
    - P: projection matrix as list of arrays
    '''
    
    K, R, T, Kh, H = [], [], [], [], []
    P = []
    
    calib = toml.load(calib_file)
    for cam in list(calib.keys()):
        if cam != 'metadata':
            K = np.array(calib[cam]['matrix'])
            Kh = np.block([K, np.zeros(3).reshape(3,1)])
            R, _ = cv2.Rodrigues(np.array(calib[cam]['rotation']))
            T = np.array(calib[cam]['translation'])
            H = np.block([[R,T.reshape(3,1)], [np.zeros(3), 1 ]])
            
            P.append(Kh.dot(H))
   
    return P
    
    
def reprojection(P_all, Q):
    '''
    Reprojects 3D point on all cameras.
    
    INPUTS:
    - P_all: list of arrays. Projection matrix for all cameras
    - Q: array of triangulated point (x,y,z,1.)

    OUTPUTS:
    - x_calc, y_calc: list of coordinates of point reprojected on all cameras
    '''
    
    x_calc, y_calc = [], []
    for c in range(len(P_all)):  
        P_cam = P_all[c]
        x_calc.append(P_cam[0].dot(Q) / P_cam[2].dot(Q))
        y_calc.append(P_cam[1].dot(Q) / P_cam[2].dot(Q))
        
    return x_calc, y_calc
    

def df_from_trc(trc_path):
    '''
    Retrieve header and data from trc path.
    '''

    # DataRate	CameraRate	NumFrames	NumMarkers	Units	OrigDataRate	OrigDataStartFrame	OrigNumFrames
    df_header = pd.read_csv(trc_path, sep="\t", skiprows=1, header=None, nrows=2, encoding="ISO-8859-1")
    header = dict(zip(df_header.iloc[0].tolist(), df_header.iloc[1].tolist()))
    
    # Label1_X  Label1_Y    Label1_Z    Label2_X    Label2_Y
    df_lab = pd.read_csv(trc_path, sep="\t", skiprows=3, nrows=1)
    labels = df_lab.columns.tolist()[2:-1:3]
    labels_XYZ = np.array([[labels[i]+'_X', labels[i]+'_Y', labels[i]+'_Z'] for i in range(len(labels))], dtype='object').flatten()
    labels_FTXYZ = np.concatenate((['Frame#','Time'], labels_XYZ))
    
    data = pd.read_csv(trc_path, sep="\t", skiprows=5, index_col=False, header=None, names=labels_FTXYZ)
    
    return header, data


def yup2zup(Q):
    '''
    Turns Y-up system coordinates into Z-up coordinates

    INPUT:
    - Q: pandas dataframe
    N 3D points as columns, ie 3*N columns in Z-up system coordinates
    and frame number as rows

    OUTPUT:
    - Q: pandas dataframe with N 3D points in Y-up system coordinates
    '''
    
    # X->Y, Y->Z, Z->X
    cols = list(Q.columns)
    cols = np.array([[cols[i*3+2],cols[i*3],cols[i*3+1]] for i in range(int(len(cols)/3))]).flatten()
    Q = Q[cols]

    return Q


def reproj_from_trc_calib_func(*args):
    '''
    Reproject 3D points from a trc file to the camera planes determined by a 
    toml calibration file.
    
    The output 2D points can be chosen to follow the DeepLabCut (default) or 
    the OpenPose format. If OpenPose is chosen, the BODY_25B model is used, 
    with ear and eye at coordinates (0,0) since they are not used by Pose2Sim. 
    You can change the BODY_25B tree if you need to reproject in OpenPose 
    format with a different model.
    
    Usage: 
    from Pose2Sim.Utilities import reproj_from_trc_calib; reproj_from_trc_calib.reproj_from_trc_calib_func(r'<input_trc_file>', r'<input_calib_file>', r'<openpose_or_deeplabcut_format>', r'<output_file_root>')
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file -f 'openpose'
    python -m reproj_from_trc_calib -t input_trc_file -c input_calib_file -f 'deeplabcut' -o output_file_root
    '''

    try:
        input_trc_file = args[0]['input_trc_file'] # invoked with argparse
        input_calib_file = args[0]['input_calib_file']
        if args[0]['openpose_or_deeplabcut_format'] == None:
            openpose_or_deeplabcut_format = 'deeplabcut'
        else:
            openpose_or_deeplabcut_format = args[0]['openpose_or_deeplabcut_format']
        if args[0]['output_file_root'] == None:
            output_file_root = input_trc_file.replace('.trc', '_reproj')
        else:
            output_file_root = args[0]['output_file_root']
    except:
        input_trc_file = args[0] # invoked as a function
        input_calib_file = args[1]
        try:
            openpose_or_deeplabcut_format = args[2]
        except:
            openpose_or_deeplabcut_format = 'deeplabcut'
        try:
            output_file_root = args[3]
        except:
            output_file_root = input_trc_file.replace('.trc', '_reproj')

    # Extract data from trc file
    header_trc, data_trc = df_from_trc(input_trc_file)
    data_trc_zup = pd.concat([data_trc.iloc[:,:2], yup2zup(data_trc.iloc[:,2:])], axis=1) # yup to zup system coordinates
    bodyparts = [d[:-2] for d in data_trc_zup.columns[2::3]]
    num_bodyparts = int(header_trc['NumMarkers'])
    filename = os.path.splitext(os.path.basename(input_trc_file))[0]
    
    # Extract data from calibration file
    P_all = computeP(input_calib_file)

    # Create camera folders
    reproj_dir = os.path.realpath(output_file_root)
    cam_dirs = [os.path.join(reproj_dir, f'cam_{cam+1:02d}_json') for cam in range(len(P_all))]
    if not os.path.exists(reproj_dir): os.mkdir(reproj_dir)  
    try:
        [os.mkdir(cam_dir) for cam_dir in cam_dirs]
    except:
        pass

    # header preparation
    columns_iterables = [['DavidPagnon'], ['person0'], bodyparts, ['x','y']]
    columns_h5 = pd.MultiIndex.from_product(columns_iterables, names=['scorer', 'individuals', 'bodyparts', 'coords'])
    rows_iterables = [['labeled_data'], [filename], [f'img_{i:03d}.png' for i in range(len(data_trc))]]
    rows_h5 = pd.MultiIndex.from_product(rows_iterables)
    data_h5 = pd.DataFrame(np.nan, index=rows_h5, columns=columns_h5)

    # Reproject 3D points on all cameras
    data_proj = [deepcopy(data_h5) for cam in range(len(P_all))] # copy data_h5 as many times as there are cameras
    Q = data_trc_zup.iloc[:,2:]
    for row in range(len(Q)):
        coords = [[] for cam in range(len(P_all))]
        for keypoint in range(num_bodyparts):
            q = np.append(Q.iloc[row,3*keypoint:3*keypoint+3], 1)
            x_all, y_all = reprojection(P_all, q)
            [coords[cam].extend([x_all[cam], y_all[cam]]) for cam in range(len(P_all))]
        for cam in range(len(P_all)):
            data_proj[cam].iloc[row,:] = coords[cam]
        
    # Save as h5 and csv if DeepLabCut format
    if openpose_or_deeplabcut_format == 'deeplabcut':
        # to h5
        h5_files = [os.path.join(cam_dir,f'{filename}_cam_{i+1:02d}.h5') for i,cam_dir in enumerate(cam_dirs)]
        [data_proj[i].to_hdf(h5_files[i], index=True, key='reprojected_points') for i in range(len(P_all))]

        # to csv
        csv_files = [os.path.join(cam_dir,f'{filename}_cam_{i+1:02d}.csv') for i,cam_dir in enumerate(cam_dirs)]
        [data_proj[i].to_csv(csv_files[i], sep=',', index=True, lineterminator='\n') for i in range(len(P_all))]

    # Save as json if OpenPose format
    elif openpose_or_deeplabcut_format == 'openpose':        
        # read body_25b tree
        bodyparts_ids = [[node.id for _, _, node in RenderTree(BODY_25B) if node.name==b][0] for b in bodyparts]
        #prepare json files
        json_dict = {'version':1.3, 'people':[]}
        json_dict['people'] = [{'person_id':[-1], 
                        'pose_keypoints_2d': np.zeros(nb_joints*3), 
                        'face_keypoints_2d': [], 
                        'hand_left_keypoints_2d':[], 
                        'hand_right_keypoints_2d':[], 
                        'pose_keypoints_3d':[], 
                        'face_keypoints_3d':[], 
                        'hand_left_keypoints_3d':[], 
                        'hand_right_keypoints_3d':[]}]
        # write one json file per camera and per frame
        for cam, cam_dir in enumerate(cam_dirs):
            for frame in range(len(Q)):
                json_dict_copy = deepcopy(json_dict)
                data_proj_frame = data_proj[cam].iloc[row]['DavidPagnon']['person0']
                # store 2D keypoints and respect body_25b keypoint order
                for (i,b) in zip(bodyparts_ids, bodyparts):
                    json_dict_copy['people'][0]['pose_keypoints_2d'][[i*3,i*3+1,i*3+2]] = np.append(data_proj_frame[b].values, 1)
                json_dict_copy['people'][0]['pose_keypoints_2d'] = json_dict_copy['people'][0]['pose_keypoints_2d'].tolist()
                # write json file
                json_file = os.path.join(cam_dir, f'{filename}_cam_{cam+1:02d}.{frame:05d}.json')
                with open(json_file, 'w') as js_f:
                    js_f.write(json.dumps(json_dict_copy))

    # Wrong format
    else:
        raise ValueError('openpose_or_deeplabcut_format must be either "openpose" or "deeplabcut"')
    
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--trc_input_file', required = True, help='trc 3D coordinates input file')
    parser.add_argument('-c', '--calib_input_file', required = True, help='toml calibration input file')
    parser.add_argument('-f', '--output_format', required=False, help='deeplabcut or openpose output format')
    parser.add_argument('-o', '--output_file', required=False, help='output file root, without extension')
    args = vars(parser.parse_args())

    reproj_from_trc_calib_func(args)