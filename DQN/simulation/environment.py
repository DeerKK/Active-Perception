import sys
import os
import subprocess
import time
import numpy.random as random
import numpy as np
import math
import PIL.Image as Image
import array
import h5py
import cv2 as cv
from scipy.ndimage.filters import uniform_filter
import pcl

try:
    from simulation.vrep import *
    print('--- Successfully load vrep ---')
except:
    print ('--------------------------------------------------------------')
    print ('"py" could not be imported. This means very probably that')
    print ('either "py" or the remoteApi library could not be found.')
    print ('Make sure both are in the same folder as this file,')
    print ('or appropriately adjust the file "py"')
    print ('--------------------------------------------------------------')
    print ('')

# TODO: 把vrep改到在后台运行（当把所有bugfit完之后），这个太卡啦，超级吃内存
# simRemoteApi.start(19999)

class Camera(object):
    """
        # kinect camera in simulation
    """
    def __init__(self, clientID, Lua_PATH):
        """
            Initialize the Camera in simulation
        """
        self.RAD2EDG = 180 / math.pi
        self.EDG2RAD = math.pi / 180
        self.Save_IMG = True
        self.Save_PATH_COLOR = r'./simulation/color'
        self.Save_PATH_DEPTH = r'./simulation/depth'
        self.Save_PATH_RES = r'./simulation/afford_h5'
        self.Lua_PATH = Lua_PATH
        self.Dis_FAR = 10
        self.depth_scale = 1000
        # self.INT16 = 65535
        self.Img_WIDTH = 512
        self.Img_HEIGHT = 424
        self.border_pos = [68,324,112,388] #up down left right of the box
        self.theta = 70
        self.Camera_NAME = r'kinect'
        self.Camera_RGB_NAME = r'kinect_rgb'
        self.Camera_DEPTH_NAME = r'kinect_depth'
        self.clientID = clientID
        self._setup_sim_camera()
        self.bg_color = np.empty((self.Img_HEIGHT, self.Img_WIDTH ,3), dtype = np.float16)
        self.bg_depth = np.empty((self.Img_HEIGHT, self.Img_WIDTH, 1), dtype = np.float16)

        self._mkdir_save(self.Save_PATH_COLOR)
        self._mkdir_save(self.Save_PATH_DEPTH)
        self._mkdir_save(self.Save_PATH_RES)

    def _mkdir_save(self, path_name):
        if not os.path.isdir(path_name):         
            os.mkdir(path_name)

    def _euler2rotm(self,theta):
        """
            -- Get rotation matrix from euler angles
        """
        R_x = np.array([[1,         0,                  0                   ],
                        [0,         math.cos(theta[0]), -math.sin(theta[0]) ],
                        [0,         math.sin(theta[0]), math.cos(theta[0])  ]
                        ])
        R_y = np.array([[math.cos(theta[1]),    0,      math.sin(theta[1])  ],
                        [0,                     1,      0                   ],
                        [-math.sin(theta[1]),   0,      math.cos(theta[1])  ]
                        ])         
        R_z = np.array([[math.cos(theta[2]),    -math.sin(theta[2]),    0],
                        [math.sin(theta[2]),    math.cos(theta[2]),     0],
                        [0,                     0,                      1]
                        ])            
        R = np.dot(R_z, np.dot( R_y, R_x ))
        return R

    def _setup_sim_camera(self):
        """
            -- Get some param and handles from the simulation scene
            and set necessary parameter for camera
        """
        # Get handle to camera
        _, self.cam_handle = simxGetObjectHandle(self.clientID, self.Camera_NAME, simx_opmode_oneshot_wait)
        _, self.kinectRGB_handle = simxGetObjectHandle(self.clientID, self.Camera_RGB_NAME, simx_opmode_oneshot_wait)
        _, self.kinectDepth_handle = simxGetObjectHandle(self.clientID, self.Camera_DEPTH_NAME, simx_opmode_oneshot_wait)
        # Get camera pose and intrinsics in simulation
        _, self.cam_position = simxGetObjectPosition(self.clientID, self.cam_handle, -1, simx_opmode_oneshot_wait)
        _, cam_orientation = simxGetObjectOrientation(self.clientID, self.cam_handle, -1, simx_opmode_oneshot_wait)

        self.cam_trans = np.eye(4,4)
        self.cam_trans[0:3,3] = np.asarray(self.cam_position)
        self.cam_orientation = [-cam_orientation[0], -cam_orientation[1], -cam_orientation[2]]
        self.cam_rotm = np.eye(4,4)
        self.cam_rotm[0:3,0:3] = np.linalg.inv(self._euler2rotm(cam_orientation))
        self.cam_pose = np.dot(self.cam_trans, self.cam_rotm) # Compute rigid transformation representating camera pose
        self._intri_camera()

    def _intri_camera(self):
        """
            Calculate the intrinstic parameters of camera
        """
        # ref: https://blog.csdn.net/zyh821351004/article/details/49786575
        fx = -self.Img_WIDTH/(2.0 * math.tan(self.theta * self.EDG2RAD / 2.0))
        fy = fx
        u0 = self.Img_HEIGHT/ 2
        v0 = self.Img_WIDTH / 2
        self.intri = np.array([[fx, 0, u0],
                               [0, fy, v0],
                               [0, 0, 1]])

    def bg_init(self):
        """
            -- use this function to save background RGB and Depth in the beginning
            -- it is used for the post process of affordance map
        """
        # self.bg_depth, self.bg_color = self.get_camera_data()
        # self.bg_color = np.asarray(self.bg_color) / 255.0
        # self.bg_depth = np.asarray(self.bg_depth) / 10000
        self.bg_depth = cv.imread('./simulation/bg/Bg_Depth.png', -1) / 10000
        self.bg_color = cv.imread('./simulation/bg/Bg_Rgb.png') / 255.0

    def get_camera_data(self):
        """
            -- Read images data from vrep and convert into np array
        """
        # Get color image from simulation
        res, resolution, raw_image = simxGetVisionSensorImage(self.clientID, self.kinectRGB_handle, 0, simx_opmode_oneshot_wait)
        # self._error_catch(res)
        color_img = np.array(raw_image, dtype=np.uint8)
        color_img.shape = (resolution[1], resolution[0], 3)
        color_img = color_img.astype(np.float)/255
        color_img[color_img < 0] += 1
        color_img *= 255
        color_img = np.fliplr(color_img)
        color_img = color_img.astype(np.uint8)

        # Get depth image from simulation
        res, resolution, depth_buffer = simxGetVisionSensorDepthBuffer(self.clientID, self.kinectDepth_handle, simx_opmode_oneshot_wait)
        # self._error_catch(res)
        depth_img = np.array(depth_buffer)
        depth_img.shape = (resolution[1], resolution[0])
        depth_img = np.fliplr(depth_img)
        depth_img[depth_img < 0] = 0
        depth_img[depth_img > 1] = 0.9999
        depth_img = depth_img * self.Dis_FAR * self.depth_scale
        self.cur_depth = depth_img
        return depth_img, color_img

    def save_image(self, cur_depth, cur_color, img_idx):
        """
            -- Save Color&Depth images
        """
        img = Image.fromarray(cur_color.astype('uint8')).convert('RGB')
        img_path = os.path.join(self.Save_PATH_COLOR, str(img_idx) + '_Rgb.png')
        img.save(img_path)
        depth_img = Image.fromarray(cur_depth.astype(np.uint32),mode='I')
        depth_path = os.path.join(self.Save_PATH_DEPTH, str(img_idx) + '_Depth.png')
        depth_img.save(depth_path)

        return depth_path, img_path

    def _error_catch(self, res):
        """
            -- Deal with error unexcepted
        """
        if res == simx_return_ok:
            print ("--- Image Exist!!!")
        elif res == simx_return_novalue_flag:
            print ("--- No image yet")
        else:
            print ("--- Error Raise")

    def hdf2affimg(self, filename):
        """
            Convert hdf5 file(output of affordance map network in lua) to img
            # Notice according to the output of the model we need to resize
        """
        h = h5py.File(filename,'r')

        res = h['results']
        res = np.array(res)
        res = res[0,1,:,:]
        resresize = cv.resize(res, (self.Img_WIDTH, self.Img_HEIGHT), interpolation=cv.INTER_CUBIC)
        resresize[np.where(resresize>1)] = 0.9999
        resresize[np.where(resresize<0)] = 0
        return resresize

    def local_patch(self, img_idx, patch_size = (128, 128)):
        """
            # according to the affordance map output
            # postprocess it and get the maximum local patch (4*128*128)
            # cascade the RGBD 4 channels and input to the agent
        """
        # first get the current img data first
        cur_depth, cur_color = self.get_camera_data()
        cur_depth_path, cur_img_path = self.save_image(cur_depth, cur_color, img_idx)
        # feed this image into affordance map network and get the h5 file
        cur_res_path = os.path.join(self.Save_PATH_RES, str(img_idx) + '_results.h5')
        affordance_cmd = 'th ' + self.Lua_PATH + ' -imgColorPath ' + cur_img_path + \
                        ' -imgDepthPath ' + cur_depth_path + ' -resultPath ' + cur_res_path
        try:
            # subprocess.call(affordance_cmd)
            os.system(affordance_cmd)
        except:
            raise Exception(' [!] !!!!!!!!!!!  Error occurred during calling affordance map')
        # get the initial affordance map from h5 file
        if os.path.isfile(cur_res_path):
            cur_afford = self.hdf2affimg(cur_res_path)
        else:
            # Use this to catch the exception for torch itself
            raise Exception(' [!] !!!!!!!!!!!  Error occurred during creating affordance map')          

        # postprocess the affordance map
        post_afford, location_2d = self._postproc_affimg(cur_color, cur_depth, cur_afford)
        print(' -- Maximum Location at {}' .format(location_2d))
        # according to the affordance map -> get the local patch with size of 4*128*128
        return self._get_patch(location_2d, cur_color, cur_depth, post_afford, patch_size)

    def _get_patch(self, location_2d, cur_color, cur_depth, post_afford, size=(128,128)):
        """
            input the postprocessed affordance map 
            return the 4*128*128 patch (cascade the depth and rgb)
        """
        y = location_2d[0]
        x = location_2d[1]
        r = int(size[0]/2)
        patch_color = cur_color[y-r:y+r,x-r:x+r,:]
        patch_depth = cur_depth[y-r:y+r,x-r:x+r]
        patch_afford = post_afford[y-r:y+r,x-r:x+r]
        patch_rgbd = np.zeros((size[0], size[1], 4))
        patch_rgbd[:,:,0:3] = patch_color
        patch_rgbd[:,:,3] = patch_depth
        return np.transpose(patch_rgbd, (2,0,1)), patch_afford, location_2d

    def _postproc_affimg(self, cur_color, cur_depth, cur_afford):
        """
            # postprocess the affordance map
            # convert from the afford_model from matlab to python
        """
        cur_color = cur_color / 255.0
        cur_depth = cur_depth / 10000
        temp = (np.abs(cur_color - self.bg_color) < 0.3)
        foregroundMaskColor = np.sum(temp, axis = 2) != 3
        backgroundDepth_mask = np.zeros(self.bg_depth.shape, dtype = bool)
        backgroundDepth_mask[self.bg_depth!=0] = True
        foregroundMaskDepth = backgroundDepth_mask & (np.abs(cur_depth-self.bg_depth) > 0.005)
        foregroundMask = (foregroundMaskColor | foregroundMaskDepth)

        x = np.linspace(0,self.Img_WIDTH-1,self.Img_WIDTH)
        y = np.linspace(0,self.Img_HEIGHT-1,self.Img_HEIGHT)
        pixX,pixY = np.meshgrid(x,y)
        camX = (pixX-self.intri[0,2])*cur_depth/self.intri[0,0]
        camY = (pixY-self.intri[1,2])*cur_depth/self.intri[1,1]
        camZ = cur_depth
        validDepth = foregroundMask & (camZ != 0) # only points with valid depth and within foreground mask

        inputPoints = [camX[validDepth],camY[validDepth],camZ[validDepth]]
        inputPoints = np.asarray(inputPoints,dtype=np.float32)
        foregroundPointcloud = pcl.PointCloud(np.transpose(inputPoints))
        foregroundNormals = self._surface_normals(foregroundPointcloud)
        
        tmp = np.zeros((foregroundNormals.size, 4), dtype=np.float16)
        for i in range(foregroundNormals.size):
            tmp[i] = foregroundNormals[i]
        foregroundNormals = np.nan_to_num(tmp[:,0:3])
        pixX = np.rint(np.dot(inputPoints[0,:],self.intri[0,0])/inputPoints[2,:]+self.intri[0,2])
        pixY = np.rint(np.dot(inputPoints[1,:],self.intri[1,1])/inputPoints[2,:]+self.intri[1,2])

        surfaceNormalsMap = np.zeros(cur_color.shape)
        arraySize = surfaceNormalsMap.shape
        pixX = pixX.astype(np.int)
        pixY = pixY.astype(np.int)
        tmp = np.ones(pixY.shape)
        tmp = tmp.astype(np.int)

        surfaceNormalsMap.ravel()[np.ravel_multi_index((pixY,pixX,tmp-1), dims=arraySize, order='C')] = foregroundNormals[:,0]
        surfaceNormalsMap.ravel()[np.ravel_multi_index((pixY,pixX,2*tmp-1), dims=arraySize, order='C')] = foregroundNormals[:,1]
        surfaceNormalsMap.ravel()[np.ravel_multi_index((pixY,pixX,3*tmp-1), dims=arraySize, order='C')] = foregroundNormals[:,2]
    
        # filter the affordance map
        tmp = self._window_stdev(surfaceNormalsMap,25)
        # accelarate the filter
        meanStdNormals = np.mean(tmp,axis = 2)
        normalBasedSuctionScores = 1 - meanStdNormals / np.max(meanStdNormals)
        cur_afford[np.where(normalBasedSuctionScores < 0.05)] = 0 
        cur_afford[np.where(foregroundMask == False)] = 0 
        post_afford = cv.GaussianBlur(cur_afford,(7,7),7)

        aff_center = post_afford[self.border_pos[0]:self.border_pos[1],self.border_pos[2]:self.border_pos[3]]
        aff_max = np.max(aff_center)
        # print(' -- Candidate Maximum location {}' .format(np.transpose(np.where(aff_center == aff_max))))
        location = np.transpose(np.where(aff_center == aff_max))[0] + \
            np.asarray([self.border_pos[0],self.border_pos[2]])
        tmp = aff_max+np.zeros(post_afford.shape)
        tmp[self.border_pos[0]:self.border_pos[1],self.border_pos[2]:self.border_pos[3]] = aff_center     
        post_afford = tmp
        return post_afford,location
        
    def _window_stdev(self, X, window_size):
        """
            std filt in np
        """
        rw = window_size
        k = ((rw*rw)/(rw*rw-1))**(0.5)
        r,c,d = X.shape
        new = np.zeros(X.shape)
        for index in range(0,d):
            XX=X[:,:,index]
            XX+=np.random.rand(r,c)*1e-6
            c1 = uniform_filter(XX, window_size, mode='reflect')
            c2 = uniform_filter(XX*XX, window_size, mode='reflect')
            new[:,:,index] = np.sqrt(c2 - c1*c1)
        return k*new

    def _sub2ind(self, arraySize, dim0Sub, dim1Sub, dim2Sub):
        """
            sub 2 ind
        """
        return np.ravel_multi_index((dim0Sub,dim1Sub,dim2Sub), dims=arraySize, order='C')

    def _surface_normals(self, cloud):
        """
            # calculate the surface normals from the cloud
        """
        ne = cloud.make_NormalEstimation()
        tree = cloud.make_kdtree()
        ne.set_SearchMethod(tree)
        ne.set_RadiusSearch(0.0001)  #this parameter influence the speed
        cloud_normals = ne.compute()
        return cloud_normals

    def pixel2ur5(self, u, v, ur5_position, push_depth, depth = 0.0, is_dst = True):
        """
            from pixel u,v and correspondent depth z -> coor in ur5 coordinate (x,y,z)
        """
        if is_dst == False:
            depth = self.cur_depth[int(u)][int(v)] / self.depth_scale

        x = depth * (u - self.intri[0][2]) / self.intri[0][0]
        y = depth * (v - self.intri[1][2]) / self.intri[1][1]
        camera_coor = np.array([x, y, depth - push_depth])
        """
            from camera coor to ur5 coor
            Notice the camera faces the plain directly and we needn't convert the depth to real z
        """
        camera_coor[2] = - camera_coor[2]
        location = camera_coor + self.cam_position - np.asarray(ur5_position)
        return location, depth
    

class UR5(object):
    """
        # ur5 arm in simulation
        # including the initial of the scene and the initial of the simulation
    """
    def __init__(self):
        self.RAD2DEG = 180 / math.pi   # 常数，弧度转度数
        self.tstep = 0.005             # 定义仿真步长
        self.targetPosition=np.zeros(3,dtype=np.float)#目标位置
        self.targetQuaternion=np.array([0.707, 0, 0.707, 0])
        # 配置关节信息
        self.jointNum = 6
        self.baseName = r'UR5'         #机器人名字
        self.ikName = r'UR5_ikTarget'
        self.jointName = r'UR5_joint'
        self.jointHandle = np.zeros((self.jointNum,), dtype=np.int) # 各关节handle
        self.jointangel=[-111.5,-22.36,88.33,28.08,-90,-21.52]
        self.position = []
        # 配置方块信息
        self.cubename= r'obj_'
        self.filename= r'test-10-obj-'
        self.scenepath = r'./simulation/scenes'
        self.cubenum = 11
        self.cubeHandle = np.zeros((self.cubenum,), dtype=np.int) # 各cubehandle
        self.obj_colors=[]
        self.obj_positions=[]
        self.obj_orientations=[]
        self.obj_order=[]

    def connect(self):  
        """
            # connect to v-rep
        """
        print('Simulation started') # 关闭潜在的连接
        simxFinish(-1) # 每隔0.2s检测一次，直到连接上V-rep 
        while True:
            self.clientID = simxStart('127.0.0.1', 19999, True, True, 5000, 5) 
            if self.clientID > -1: 
                break 
            else: 
                time.sleep(0.2) 
                print("Failed connecting to remote API server!") 
        print("Connection success!")
        for i in range(self.cubenum):
            _, returnHandle = simxGetObjectHandle(self.clientID, self.cubename + str(i), simx_opmode_blocking) 
            self.cubeHandle[i] = returnHandle 
        simxSetFloatingParameter(self.clientID, sim_floatparam_simulation_time_step, self.tstep, simx_opmode_oneshot) # 保持API端与V-rep端相同步长
        simxSynchronous(self.clientID, True) # 然后打开同步模式 
        simxStartSimulation(self.clientID, simx_opmode_oneshot)
        # Get the location of the ur5
        _, self.ur5_handle = simxGetObjectHandle(self.clientID, self.baseName, simx_opmode_oneshot_wait)
        _, self.position = simxGetObjectPosition(self.clientID, self.ur5_handle, -1, simx_opmode_oneshot_wait)

    def ankleinit(self):
        """
            # initial the ankle angle for ur5
        """
        for i in range(self.jointNum):
            _, returnHandle = simxGetObjectHandle(self.clientID, self.jointName + str(i+1), simx_opmode_blocking) 
            self.jointHandle[i] = returnHandle
        simxSynchronousTrigger(self.clientID) # 让仿真走一步 
        for i in range(self.jointNum):
            simxPauseCommunication(self.clientID, True) 
            simxSetJointTargetPosition(self.clientID, self.jointHandle[i],self.jointangel[i]/self.RAD2DEG, simx_opmode_oneshot)  #设置关节角
            simxPauseCommunication(self.clientID, False)
            simxSynchronousTrigger(self.clientID) # 进行下一步 
            simxGetPingTime(self.clientID) # 使得该仿真步走完
        _, self.ur5_hand_handle = simxGetObjectHandle(self.clientID, self.ikName, simx_opmode_oneshot_wait)
        _, self.hand_init_pos = simxGetObjectPosition(self.clientID, self.ur5_hand_handle, -1, simx_opmode_oneshot_wait)

    def cubeinit(self, filenum):
        """
            initial the scene (the arrangement of the blocks)
        """
        fileadd=os.path.join(self.scenepath, self.filename+str('%02d' % filenum)+'.txt')
        fs = open(fileadd, 'r')
        file_content = fs.readlines()
        for object_idx in range(self.cubenum):
            file_content_curr_object = file_content[object_idx].split()
            self.obj_order.append(file_content_curr_object[0])
            self.obj_positions.append([float(file_content_curr_object[1]),float(file_content_curr_object[2]),float(file_content_curr_object[3])])
            self.obj_orientations.append([float(file_content_curr_object[4]),float(file_content_curr_object[5]),float(file_content_curr_object[6])])
        fs.close()
        for j in range(self.cubenum):
            i=int(self.obj_order[j])
            simxPauseCommunication(self.clientID, True) 
            simxSetObjectOrientation(self.clientID,self.cubeHandle[i],-1,self.obj_orientations[j],simx_opmode_oneshot)
            simxPauseCommunication(self.clientID, False)
            simxPauseCommunication(self.clientID, True) 
            simxSetObjectPosition(self.clientID,self.cubeHandle[i],-1,self.obj_positions[j],simx_opmode_oneshot)
            simxPauseCommunication(self.clientID, False)

    def disconnect(self):
        """
            # disconnect from v-rep
            # and stop simulation
        """
        simxStopSimulation(self.clientID,simx_opmode_oneshot)
        simxFinish(self.clientID)
        print ('Simulation ended!')
    
    def get_clientID(self):
        return self.clientID

    def get_position(self):
        return self.position

    def ur5act(self, move_begin, move_to):
        """
            The action of the ur5 in a single act including:
            Get to push beginning
            Push to the destination
            Return to the init pose
        """
        self.grasp()
        self.ur5moveto(move_begin)
        time.sleep(0.2)
        # input('?? ')
        self.ur5moveto(move_to)
        time.sleep(0.2)
        # input('?? ')
        # Return to the initial pose
        self.ur5moveto([0.3, 0, 0.5])#TODO: self.hand_init_pos)
        time.sleep(0.2)
        self.lose()

    def ur5moveto(self, dst_location):
        """
            Push the ur5 hand to the location of dst_location
        """
        simxSynchronousTrigger(self.clientID) # 让仿真走一步 
        self.targetPosition = dst_location
        simxPauseCommunication(self.clientID, True)    #开启仿真
        simxSetIntegerSignal(self.clientID, 'ICECUBE_0', 21, simx_opmode_oneshot)
        for i in range(3):
            simxSetFloatSignal(self.clientID, 'ICECUBE_'+str(i+1),self.targetPosition[i],simx_opmode_oneshot)
        for i in range(4):
            simxSetFloatSignal(self.clientID, 'ICECUBE_'+str(i+4),self.targetQuaternion[i], simx_opmode_oneshot)
        simxPauseCommunication(self.clientID, False)
        simxSynchronousTrigger(self.clientID) # 进行下一步 
        simxGetPingTime(self.clientID) # 使得该仿真步走完

    def grasp(self):
        simxSetIntegerSignal(self.clientID,'RG2CMD',1,simx_opmode_blocking)

    def lose(self):
        simxSetIntegerSignal(self.clientID,'RG2CMD',0,simx_opmode_blocking)

    def getcubepos(self):
        for j in range(self.cubenum):
            i=int(self.obj_order[j])
            _,self.obj_positions=simxGetObjectPosition(self.clientID,self.cubeHandle[i],-1,simx_opmode_blocking)
            _,self.obj_orientations=simxGetObjectOrientation(self.clientID,self.cubeHandle[i],-1,simx_opmode_blocking)
            print(self.obj_positions+self.obj_orientations)

class DQNEnvironment(object):
    """
        # environment for training of DQN
    """
    def __init__(self, config):
        self.Lua_PATH = config.Lua_PATH
        self.End_Metric = config.end_reward
        self.scene_num = config.scene_num
        self.EDG2RAD = math.pi / 180
        # initial the ur5 arm in simulation
        self.ur5 = UR5()
        self.ur5.connect()
        self.ur5.ankleinit()
        self.ur5_location = self.ur5.get_position()
        # initial the camera in simulation
        self.clientID = self.ur5.get_clientID()
        self.camera = Camera(self.clientID, self.Lua_PATH)
        self.camera.bg_init()

        self.terminal = False
        self.reward = 0
        self.action = -1
        self.inChannel = config.inChannel
        self.screen_height = config.screen_height
        self.screen_width = config.screen_width
        self.location_2d = [self.camera.Img_HEIGHT//2, self.camera.Img_WIDTH//2]
        self.screen = np.empty((self.inChannel, self.screen_height, self.screen_width))
        self.index = -1
        self.metric = 0
        self.save_size = 500 # use this params is for over-storage of early img in disk -> which used for the affordance input

    def new_scene(self):
        """
            Random initial the scene
            # scene index is from 0~self.scene_num-1
        """
        scene_num = random.randint(0, self.scene_num)
        print(' [*] Random init the scene %2d' %(scene_num))
        self.ur5.cubeinit(scene_num)
        # return the camera_data
        self.index = (self.index + 1)% self.save_size
        # location_2d stores the maximum affordance value coor know in the scene
        self.screen, self.local_afford_past, self.location_2d = self.camera.local_patch(self.index, (self.screen_height, self.screen_width))
        self.local_afford_new = self.local_afford_past
        self.metric = self.reward_metric(self.local_afford_new)
        self.terminal = self.ifterminal()
        return self.screen, 0., -1, self.terminal

    def close(self):
        """
            End the simulation
        """
        self.ur5.disconnect()

    def act(self, action, is_training=True):
        """
            first convert the action to (x,y,depth)
            then convert x,y,depth to pixel coor(according to the location_2d)
            then convert to coor in ur5
            then act it
            then take camera data and apply the local_patch again -> get new local_afford
            use this two affordance map -> reward
            use new affordance map -> terminal
        """
        # act on the scene

        move_begin, move_to = self.action2ur5(action)
        print(' -- Push to {}' .format(move_to))
        self.ur5.ur5act(move_begin, move_to)
        time.sleep(1) # Wait for the ur5 to move to init location
        # get the new camera_data
        self.index = (self.index + 1)% self.save_size
        # location_2d stores the maximum affordance value coor know in the scene
        self.local_afford_past = self.local_afford_new
        self.screen, self.local_afford_new, self.location_2d = self.camera.local_patch(self.index, (self.screen_height, self.screen_width))
        
        self.reward = self.calc_reward()
        self.terminal = self.ifterminal()
        return self.screen, self.reward, self.terminal

    def calc_reward(self):
        """
            Use two affordance map to calculate the reward
        """
        last_metric = self.metric
        self.metric = self.reward_metric(self.local_afford_new)
        if (self.metric - last_metric) > 0. :
            return 1.
        else:
            return -1.

    def ifterminal(self):
        """
            Use the self.local_afford_new to judge if terminal
        """
        return self.metric > self.End_Metric

    def reward_metric(self, afford_map):
        """
            -- calculate the metric on a single affordance map
            -- for now we weight three values() 
            1. distance between two peaks in the local patch
            2. flatten level of the center peaks
            3. the value of the center peaks
        """

        half_screen = self.screen_height // 2
        peaklocation = []
        rr = 2
        peakjudge = 0.5

        # define local peak as the maximum num in area with radius = rr
        peaknum = 0
        for i in range(rr,self.screen_height-rr-1):
            for j in range(rr,self.screen_width-rr-1):
                tmp = afford_map[i-rr:i+rr+1,j-rr:j+rr+1]
                local_value = tmp[rr, rr]
                tmp[rr, rr] = 0
                if local_value > np.max(tmp) and local_value > peakjudge:
                    peaknum += 1
                    peaklocation.append((i,j))
        peak_dis= 0.
        for i in range(0,peaknum):
            peak_dis += ((peaklocation[i][0]-half_screen) **2 + (peaklocation[i][1]-half_screen) **2) **0.5
        if peaknum == 0:
            reg_peak_dis = 0
        else:
            avg_peak_dis = peak_dis / peaknum
            reg_peak_dis = avg_peak_dis * 1.414 / self.screen_height

        center_value = afford_map[half_screen][half_screen]
        affmax = center_value + np.zeros(afford_map.shape)
        flatten = np.sum((affmax - afford_map) **2)/(afford_map.size - 1)

        metric = 0.4*(1-reg_peak_dis) + 0.4*flatten + 0.2*center_value
        print(' -- Metric for current frame: %f' %(metric))
        return metric

    def action2ur5(self, action):
        """
            first convert the action to (x,y,depth)
            then convert x,y,depth to pixel coor(according to the location_2d)
            then convert to coor in ur5

            Including the beginning point and destination point
        """
        # 96, 96 is the output of the u-net
        idx = np.unravel_index(action, (96, 96, 16))
        relate_local = list(idx[0:2])
        ori_depth_idx = np.unravel_index(int(idx[2]), (8,2))
        ori = ori_depth_idx[0] * 360. / 8.
        push_depth = ori_depth_idx[1] * (-0.04) # choose in current depth or 4cm deeper one
        # (ori_depth_idx[1] - 0.5) * 0.04 # choose in two depth -0.02 or 0.02 (deeper than the pixel depth) TODO:
        push_dis = self.screen_height / 4 # fix the push distance in 32 pixel TODO:

        # seems the output of the u-net is the same size of input so we need to resize the output idx
        relate_local = (np.asarray(relate_local) + 1.0) * self.screen_height / 96 - 1.0
        relate_local = np.round(relate_local)
        real_local = self.location_2d + relate_local - self.screen_height // 2
        # -> to the new push point with dest ori and depth
        real_dest = []
        real_dest.append (real_local[0] + push_dis * math.cos(ori*self.EDG2RAD))
        real_dest.append (real_local[1] + push_dis * math.sin(ori*self.EDG2RAD))
        # from pixel coor to real ur5 coor
        move_begin, src_depth = self.camera.pixel2ur5(real_local[0], real_local[1], self.ur5_location, push_depth, is_dst = False)
        move_to, _ = self.camera.pixel2ur5(real_dest[0], real_dest[1], self.ur5_location, push_depth, src_depth, is_dst = True)
        return move_begin, move_to
