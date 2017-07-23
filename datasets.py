from __future__ import print_function
import torch.utils.data as data
from PIL import Image
import os
import os.path
import errno
import torch
import json
import codecs
import numpy as np
import progressbar
import sys
import torchvision.transforms as transforms
import utils
import argparse
import json
from numpy.linalg import inv
import pickle


IMG_EXTENSIONS = [
    '.jpg', '.JPG', '.jpeg', '.JPEG',
    '.png', '.PNG', '.ppm', '.PPM', '.bmp', '.BMP',
]

def is_image_file(filename):
    return any(filename.endswith(extension) for extension in IMG_EXTENSIONS)

def default_loader(path):
    img = Image.open(path).convert('RGB')
    return img

def depth_loader(path):
    img = Image.open(path).convert('I')
    return img

class ViewDataSet3D(data.Dataset):

    def __init__(self, root, train=True, transform=None, target_transform=None, loader=default_loader, seqlen=5, debug=False, dist_filter = None, off_3d = False, dist_filter2 = None):
        print ('Processing the data:')
        self.root = root
        #print(self.root)
        self.scenes = sorted([d for d in (os.listdir(self.root)) if os.path.isdir(os.path.join(self.root, d)) and os.path.isfile(os.path.join(self.root, d, 'sweep_locations.csv')) and os.path.isdir(os.path.join(self.root, d, 'pano'))])
        #print(self.scenes)
        num_scenes = len(self.scenes)
        num_train = int(num_scenes * 0.9)
        print("Total %d scenes %d train %d test" %(num_scenes, num_train, num_scenes - num_train))
        if train:
            self.scenes = self.scenes[:num_train]
        else:
            self.scenes = self.scenes[num_train:]


        self.bar  = progressbar.ProgressBar(widgets=[
                    ' [', progressbar.Timer(), '] ',
                    progressbar.Bar(),
                    ' (', progressbar.ETA(), ') ',
                    ])

        self.meta = {}
        if debug:
            last = 35
        else:
            last = len(self.scenes)

        for scene in self.scenes[:last]:
            posefile = os.path.join(self.root, scene, 'sweep_locations.csv')
            with open(posefile) as f:
                for line in f:
                    l = line.strip().split(',')
                    if not self.meta.has_key(scene):
                        self.meta[scene] = {}
                    metadata = (l[0], map(float, l[1:4]), map(float, l[4:8]))

                    if os.path.isfile(os.path.join(self.root, scene, 'pano', 'points', 'point_' + l[0] + '.json')):
                        self.meta[scene][metadata[0]] = metadata

        self.train = train
        self.loader = loader
        self.seqlen = seqlen
        self.transform = transform
        self.target_transform = target_transform
        self.off_3d = off_3d
        self.select = []
        if self.transform:
            self.depth_trans = transforms.Compose(self.transform.transforms[:-1])
        else:
            self.depth_trans = None

        print("Indexing")
        for scene, meta in self.bar(self.meta.items()):
            if len(meta) < self.seqlen:
                continue
            for uuid,v in meta.items():
                dist_list = [(uuid2, np.linalg.norm(np.array(v2[1]) - np.array(v[1]))) for uuid2,v2 in meta.items()]
                dist_list = sorted(dist_list, key = lambda x:x[-1])

                if not dist_filter is None:
                    if dist_list[1][-1] < dist_filter:
                        self.select.append([[scene, dist_list[i][0], dist_list[i][1]] for i in range(self.seqlen)])
                    
                else:
                    self.select.append([[scene, dist_list[i][0], dist_list[i][1]] for i in range(self.seqlen)])
                
    def __getitem__(self, index):
        #print(index)
        scene = self.select[index][0][0]
        #print(scene)
        uuids = [item[1] for item in self.select[index]]
        #print(uuids)
        #poses = ([self.meta[scene][item][1:] for item in uuids])
        #poses = [item[0] + item[1] for item in poses]
        #poses = [torch.from_numpy(np.array(item, dtype=np.float32)) for item in poses]
        paths = ([os.path.join(self.root, scene, 'pano', 'rgb', "point_" + item + "_view_equirectangular_domain_rgb.png") for item in uuids])
        mist_paths = ([os.path.join(self.root, scene, 'pano', 'mist', "point_" + item + "_view_equirectangular_domain_mist.png") for item in uuids])
        normal_paths = ([os.path.join(self.root, scene, 'pano', 'normal', "point_" + item + "_view_equirectangular_domain_normal.png") for item in uuids])
        pose_paths = ([os.path.join(self.root, scene, 'pano', 'points', "point_" + item + ".json") for item in uuids])
        #print(paths)
        poses = []
        #print(pose_paths)
        for item in pose_paths:
            f = open(item)
            pose_dict = json.load(f)
            p = np.concatenate(np.array(pose_dict[0][u'camera_rt_matrix'] + [[0,0,0,1]])).astype(np.float32).reshape((4,4))
            #print(p,p.shape)

            poses.append(p)
            f.close()

        img_paths = paths[1:]
        target_path = paths[0]
        img_poses = poses[1:]
        target_pose = poses[0]

        mist_img_paths = mist_paths[1:]
        mist_target_path = mist_paths[0]

        normal_img_paths = normal_paths[1:]
        normal_target_path = normal_paths[0]
        poses_relative = []

        for item in img_poses:
            relative = np.dot(item, inv(target_pose))
            poses_relative.append(torch.from_numpy(np.concatenate(utils.transfromM(relative), 0).astype(np.float32)))

        #print(poses_relative)

        imgs = [self.loader(item) for item in img_paths]
        target = self.loader(target_path)

        if not self.off_3d:
            mist_imgs = [depth_loader(item) for item in mist_img_paths]
            mist_target = depth_loader(mist_target_path)




            normal_imgs = [self.loader(item) for item in normal_img_paths]
            normal_target = self.loader(normal_target_path)


        rpose = utils.transfromM(relative)

        if not self.transform is None:
            imgs = [self.transform(item) for item in imgs]
        if not self.target_transform is None:
            target = self.target_transform(target)

        if not self.off_3d:
            if not self.transform is None:
                mist_imgs = [self.depth_trans(item) for item in mist_imgs]
            if not self.target_transform is None:
                mist_target = self.depth_trans(mist_target)


            mist_imgs = [torch.from_numpy(np.array(item).astype(np.float32)/(65536.0)) for item in mist_imgs]
            mist_target = torch.from_numpy(np.array(mist_target).astype(np.float32)/(65536.0))


            if not self.transform is None:
                normal_imgs = [self.transform(item) for item in normal_imgs]
            if not self.target_transform is None:
                normal_target = self.target_transform(normal_target)

        if self.off_3d:
            return imgs, target, poses_relative
        else:
            return imgs, target, mist_imgs, mist_target, normal_imgs, normal_target,  poses_relative

    def __len__(self):
        return len(self.select)

    
class Places365Dataset(data.Dataset):
    def __init__(self, root, train=True, transform=None, loader=default_loader):
        self.root = root
      
        self.train = train
        self.fns = []
        self.fofn = 'fofn'+str(int(train))+'.pkl'
        self.loader = loader
        self.transform = transform
        if not os.path.isfile(self.fofn):
            for subdir, dirs, files in os.walk(self.root):
                if self.train:
                    files = files[:len(files) / 10 * 9]
                else:
                    files = files[len(files) / 10 * 9:]
                print(subdir)
                for file in files:
                    self.fns.append(os.path.join(subdir, file))
            with open(self.fofn, 'wb') as fp:
                pickle.dump(self.fns, fp)
        else:
            with open(self.fofn, 'rb') as fp:
                self.fns = pickle.load(fp)
              
    def __len__(self):
        return len(self.fns)
    
    def __getitem__(self, index):
        path = self.fns[index]
        img = self.loader(path)
        if not self.transform is None:
            img = self.transform(img)
        return img
    
if __name__ == '__main__':
    print('test')
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug'  , action='store_true', help='debug mode')
    parser.add_argument('--dataroot', required=True, help='path to dataset')
    parser.add_argument('--dataset'  , required = True, help='dataset type')
    opt = parser.parse_args()

    if opt.dataset == 'view3d':
        d = ViewDataSet3D(root=opt.dataroot, debug=opt.debug, seqlen = 2, dist_filter = 0.8, dist_filter2 = 2.0)
        print(len(d))
        sample = (d[1])
        print(sample)
        if sample is not None:
            print('3d test passed')
    elif opt.dataset == 'places365':
        d = Places365Dataset(root = opt.dataroot)
        print(len(d))
        sample = d[0]
        print(sample)
        if sample is not None:
            print('places 365 test passed')
