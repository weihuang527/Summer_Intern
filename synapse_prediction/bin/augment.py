import numpy as np
from scipy.ndimage.interpolation import map_coordinates, zoom
from libs.coordinate import Coordinate
import time
import random
import math
from skimage.draw import line
from scipy.ndimage.measurements import label
from scipy.ndimage.morphology import binary_dilation

def augmentflip(data, rule):
    # data: copy of the original input
    """Flip data according to a specified rule.
    Args:
        data:   4D numpy array to be transformed.
        rule:   Transform rule, specified as a Boolean array.
                [z reflection, y reflection, x reflection, xy transpose]
    Returns:
        Transformed data.
    """
    assert np.size(rule) == 4 and data.ndim == 3

    # z reflection.
    if rule[0]:
        data = data[::-1, :, :]
    # x reflection.
    if rule[1]:
        data = data[:, :, ::-1]
    # y reflection.
    if rule[2]:
        data = data[:, ::-1, :]
    # Transpose in xy.
    if rule[3]:
        data = data.transpose(0, 2, 1)
    return data


class GreyAugment():
    """
    Greyscale value augmentation.
    Randomly adjust contrast/brightness, and apply random gamma correction.
    """

    def __init__(self, seednum=1234, mode='3D', skip_ratio=0.3, CONTRAST_FACTOR=0.3, BRIGHTNESS_FACTOR=0.3):
        """
        Initialize parameters.
        Args:
            mode: 2D, 3D, or mix
            skip_ratio:
        """
        assert mode == '3D' or mode == '2D' or mode == 'mix'
        self.mode = mode
        self.ratio = skip_ratio
        self.CONTRAST_FACTOR = CONTRAST_FACTOR
        self.BRIGHTNESS_FACTOR = BRIGHTNESS_FACTOR
        self.seednum = seednum

    def augment(self, imgs):

        np.random.seed(self.seednum)
        #ret = sample
        skiprand = np.random.rand()
        print (skiprand)
        if skiprand > self.ratio:
            if self.mode == 'mix':
                mode_ = '3D' if skiprand > 0.65 else '2D'  # [0.3,1]
            else:
                mode_ = self.mode
            if mode_ == '2D':
                imgs = self.augment2D(imgs)
            elif mode_ == '3D':
                imgs = self.augment3D(imgs)
            print (mode_)
            return imgs
        else:
            print ('skip')
            return imgs
           # ret = eval('self.augment{}(sample, **kwargs)'.format(mode))
        #return ret

    def augment2D(self, imgs):
        """
        Adapted from ELEKTRONN (http://elektronn.org/).
        """
        #print '2D greyscale augmentation'  # DEBUG

        # Greyscale augmentation.
        np.random.seed(self.seednum)
        for z in range(imgs.shape[-3]):
            img = imgs[z, :, :]
            img *= 1 + (np.random.rand() - 0.5)*self.CONTRAST_FACTOR
            img += (np.random.rand() - 0.5)*self.BRIGHTNESS_FACTOR
            img = np.clip(img, 0, 1)
            img **= 2.0**(np.random.rand()*2 - 1)
            imgs[z, :, :] = img

        return imgs

    def augment3D(self, imgs):
        """
        Adapted from ELEKTRONN (http://elektronn.org/).
        """
        #print '3D greyscale augmentation'  # DEBUG

        # Greyscale augmentation.
        np.random.seed(self.seednum)
        imgs *= 1 + (np.random.rand() - 0.5)*self.CONTRAST_FACTOR
        imgs += (np.random.rand() - 0.5)*self.BRIGHTNESS_FACTOR
        imgs = np.clip(imgs, 0, 1)
        imgs **= 2.0**(np.random.rand()*2 - 1)

        return imgs


def create_identity_transformation(shape, subsample=1):

    dims = len(shape)
    subsample_shape = tuple(max(1, int(s/subsample)) for s in shape)
    step_width = tuple(float(shape[d]-1)/(subsample_shape[d]-1)
                       if subsample_shape[d] > 1 else 1 for d in range(dims))

    axis_ranges = (
        np.arange(subsample_shape[d], dtype=np.float32)*step_width[d]
        for d in range(dims)
    )
    return np.array(np.meshgrid(*axis_ranges, indexing='ij'), dtype=np.float32)


def upscale_transformation(transformation, output_shape, interpolate_order=1):

    input_shape = transformation.shape[1:]

    # print("Upscaling control points")
    # print("\tfrom               : " + str(input_shape))
    # print("\tto                 : " + str(output_shape))
    # print("\tinterpolation order: " + str(interpolate_order))

    dims = len(output_shape)
    scale = tuple(float(s)/c for s, c in zip(output_shape, input_shape))

    #start = time.time()
    scaled = np.zeros((dims,)+output_shape, dtype=np.float32)
    for d in range(dims):
        zoom(transformation[d], zoom=scale,
             output=scaled[d], order=interpolate_order)
    # print("\tupsampled in " + str(time.time() - start) + "s")

    return scaled


def create_elastic_transformation(shape, control_point_spacing=100, jitter_sigma=10.0, subsample=1):

    dims = len(shape)
    subsample_shape = tuple(max(1, int(s/subsample)) for s in shape)

    try:
        spacing = tuple((d for d in control_point_spacing))
    except:
        spacing = (control_point_spacing,)*dims
    try:
        sigmas = [s for s in jitter_sigma]
    except:
        sigmas = [jitter_sigma]*dims

    control_points = tuple(
        max(1, int(round(float(shape[d])/spacing[d])))
        for d in range(len(shape))
    )

    # print("Creating elastic transformation with:")
    # print("\tcontrol points per axis: " + str(control_points))
    # print("\taxis jitter sigmas     : " + str(sigmas))

    # jitter control points
    control_point_offsets = np.zeros(
        (dims,) + control_points, dtype=np.float32)
    for d in range(dims):
        if sigmas[d] > 0:
            control_point_offsets[d] = np.random.normal(
                scale=sigmas[d], size=control_points)

    return upscale_transformation(control_point_offsets, subsample_shape, interpolate_order=3)


def rotate(point, angle):

    res = np.array(point)
    res[0] = math.sin(angle)*point[1] + math.cos(angle)*point[0]
    res[1] = -math.sin(angle)*point[0] + math.cos(angle)*point[1]

    return res


def create_rotation_transformation(shape, angle, subsample=1):

    dims = len(shape)
    subsample_shape = tuple(max(1, int(s/subsample)) for s in shape)
    control_points = (2,)*dims

    # map control points to world coordinates
    control_point_scaling_factor = tuple(float(s-1) for s in shape)

    # rotate control points
    center = np.array([0.5*(d-1) for d in shape])

    # print("Creating rotation transformation with:")
    # print("\tangle : " + str(angle))
    # print("\tcenter: " + str(center))

    control_point_offsets = np.zeros(
        (dims,) + control_points, dtype=np.float32)
    for control_point in np.ndindex(control_points):

        point = np.array(control_point)*control_point_scaling_factor
        center_offset = np.array(
            [p-c for c, p in zip(center, point)], dtype=np.float32)
        rotated_offset = np.array(center_offset)
        rotated_offset[-2:] = rotate(center_offset[-2:], angle)
        displacement = rotated_offset - center_offset
        control_point_offsets[(slice(None),) + control_point] += displacement

    return upscale_transformation(control_point_offsets, subsample_shape)


def random_offset(max_misalign):

    return Coordinate((0,) + tuple(max_misalign - random.randint(0, 2*int(max_misalign)) for d in range(2)))

def misalign(transformation,prob_slip,prob_shift,max_misalign):
    num_sections = transformation[0].shape[0]
    print (num_sections)
    shifts = [Coordinate((0,0,0))]*num_sections
    for z in range(num_sections):
        r = random.random()
        #print (r)
        if r <= prob_slip:
            shifts[z] = random_offset(max_misalign)
            #print ('shifts '+str(shifts[z]))
        elif r <= prob_slip + prob_shift:
            offset = random_offset(max_misalign)
            for zp in range(z, num_sections):
                shifts[zp] += offset
                #print ('shiftzp '+str(shifts[zp]))
    #print ("misaligning sections with " + str(shifts))

    for z in range(num_sections):
        transformation[1][z,:,:] += shifts[z][1]
        transformation[2][z,:,:] += shifts[z][2]
    return transformation


class ElasticAugment():
    '''Elasticly deform a batch. Requests larger batches upstream to avoid data 
    loss due to rotation and jitter.
    Args:
        control_point_spacing (``tuple`` of ``int``):
            Distance between control points for the elastic deformation, in
            voxels per dimension.
        jitter_sigma (``tuple`` of ``float``):
            Standard deviation of control point jitter distribution, in voxels
            per dimension.
        rotation_interval (``tuple`` of two ``floats``):
            Interval to randomly sample rotation angles from (0, 2PI).
        prob_slip (``float``):
            Probability of a section to "slip", i.e., be independently moved in
            x-y.
        prob_shift (``float``):
            Probability of a section and all following sections to move in x-y.
        max_misalign (``int``):
            Maximal voxels to shift in x and y. Samples will be drawn
            uniformly. Used if ``prob_slip + prob_shift`` > 0.
        subsample (``int``):
            Instead of creating an elastic transformation on the full
            resolution, create one subsampled by the given factor, and linearly
            interpolate to obtain the full resolution transformation. This can
            significantly speed up this node, at the expense of having visible
            piecewise linear deformations for large factors. Usually, a factor
            of 4 can savely by used without noticable changes. However, the
            default is 1 (i.e., no subsampling).
    '''

    def __init__(
            self,
            control_point_spacing,
            jitter_sigma,
            rotation_interval,
            prob_slip=0,
            prob_shift=0,
            max_misalign=0,
            subsample=1):

        self.control_point_spacing = control_point_spacing
        self.jitter_sigma = jitter_sigma
        self.rotation_start = rotation_interval[0]
        self.rotation_max_amount = rotation_interval[1] - rotation_interval[0]
        self.prob_slip = prob_slip
        self.prob_shift = prob_shift
        self.max_misalign = max_misalign
        self.subsample = subsample

    def create_transformation(self, target_shape):

        transformation = create_identity_transformation(
            target_shape,
            subsample=self.subsample)
        # shape: channel,d,w,h

        if sum(self.jitter_sigma) > 0:
            transformation += create_elastic_transformation(
                target_shape,
                self.control_point_spacing,
                self.jitter_sigma,
                subsample=self.subsample)

        rotation = random.random()*self.rotation_max_amount + self.rotation_start
        if rotation != 0:
            transformation += create_rotation_transformation(
                target_shape,
                rotation,
                subsample=self.subsample)

        if self.subsample > 1:
            transformation = upscale_transformation(
                transformation,
                target_shape)

        if self.prob_slip + self.prob_shift > 0:
            misalign(transformation, self.prob_slip,
                     self.prob_shift, self.max_misalign)

        return transformation


def apply_transformation(image, transformation, interpolate= True, outside_value = 0, output = None):

    # print("Applying transformation...")
    order = 1 if interpolate == True else 0
    output = image.dtype if output is None else output
    return map_coordinates(image, transformation, output=output, order=order, mode='constant', cval=outside_value)


def prepare_deform_slice(slice_shape, deformation_strength, iterations, randomseed):
    # grow slice shape by 2 x deformation strength
    np.random.seed(randomseed)
    grow_by = 2 * deformation_strength
    #print ('sliceshape: '+str(slice_shape[0])+' growby: '+str(grow_by)+ ' strength: '+str(deformation_strength))
    shape = (slice_shape[0] + grow_by, slice_shape[1] + grow_by)
    # randomly choose fixed x or fixed y with p = 1/2
    fixed_x = np.random.random() < .5
    if fixed_x:
        x0, y0 = 0, np.random.randint(1, shape[1] - 2)
        x1, y1 = shape[0] - 1, np.random.randint(1, shape[1] - 2)
    else:
        x0, y0 = np.random.randint(1, shape[0] - 2), 0
        x1, y1 = np.random.randint(1, shape[0] - 2), shape[1] - 1

    ## generate the mask of the line that should be blacked out
    #print (shape)
    line_mask = np.zeros(shape, dtype='bool')
    rr, cc = line(x0, y0, x1, y1)
    line_mask[rr, cc] = 1

    # generate vectorfield pointing towards the line to compress the image
    # first we get the unit vector representing the line
    line_vector = np.array([x1 - x0, y1 - y0], dtype='float32')
    line_vector /= np.linalg.norm(line_vector)
    # next, we generate the normal to the line
    normal_vector = np.zeros_like(line_vector)
    normal_vector[0] = - line_vector[1]
    normal_vector[1] = line_vector[0]

    # make meshgrid
    x, y = np.meshgrid(np.arange(shape[1]), np.arange(shape[0]))
    # generate the vector field
    flow_x, flow_y = np.zeros(shape), np.zeros(shape)

    # find the 2 components where coordinates are bigger / smaller than the line
    # to apply normal vector in the correct direction
    components, n_components = label(np.logical_not(line_mask).view('uint8'))
    assert n_components == 2, "%i" % n_components
    neg_val = components[0, 0] if fixed_x else components[-1, -1]
    pos_val = components[-1, -1] if fixed_x else components[0, 0]

    flow_x[components == pos_val] = deformation_strength * normal_vector[1]
    flow_y[components == pos_val] = deformation_strength * normal_vector[0]
    flow_x[components == neg_val] = - deformation_strength * normal_vector[1]
    flow_y[components == neg_val] = - deformation_strength * normal_vector[0]

    # generate the flow fields
    flow_x, flow_y = (x + flow_x).reshape(-1, 1), (y + flow_y).reshape(-1, 1)

    # dilate the line mask
    line_mask = binary_dilation(line_mask, iterations=iterations)  # default=10

    return flow_x, flow_y, line_mask


def deform_2d(image2d, deformation_strength, iterations, randomseed):
    flow_x, flow_y, line_mask = prepare_deform_slice(
        image2d.shape, deformation_strength, iterations, randomseed)
    section = image2d.squeeze()
    mean = section.mean()
    shape = section.shape
    #interpolation=3
    section = map_coordinates(section, (flow_y, flow_x), mode='constant',
                              order=3).reshape(int(flow_x.shape[0]**0.5), int(flow_x.shape[0]**0.5))
    section = np.clip(section, 0., 1.)
    section[line_mask] = mean
    return section


def apply_deform(imgs, masks, deformation_strength=20, iterations=10, deform_ratio=0.08):
    '''
    imgs,masks :3D
    use same seed 
    '''
    transformedimgs, transformedmasks = {}, {}
    sectionsnum = imgs.shape[0]
    for i in range(sectionsnum):
        if random.random() <= deform_ratio:
            randomseed = np.random.randint(1000000)
            transformedimgs[i] = deform_2d(
                imgs[i], deformation_strength, iterations, randomseed)
            transformedmasks[i] = deform_2d(
                masks[i], deformation_strength, iterations, randomseed)
        else:
            transformedimgs[i] = imgs[i]
            transformedmasks[i] = masks[i]
    return transformedimgs, transformedmasks
