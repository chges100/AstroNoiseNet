from os import listdir
from os.path import isfile, join
import numpy as np

import warnings
warnings.simplefilter('ignore', np.RankWarning)

import tensorflow as tf
import tensorflow.keras as K
import tensorflow.keras.layers as L
import copy
import pickle
import scipy
from astropy.io import fits
from matplotlib import pyplot as plt
from matplotlib.colors import rgb_to_hsv, hsv_to_rgb 


from stretch import stretch
from pridnet import pridnet
from unet import unet
from ridnet import ridnet
from config import Config, load_config

from IPython import display

class Net():
    def __init__(self, config:Config):

        assert config["mode"] in ['RGB', 'Greyscale'], "Mode should be either RGB or Greyscale"
        self.mode = config["mode"]
        if self.mode == 'RGB': self.input_channels = 3
        else: self.input_channels = 1

        self.window_size = config["window_size"]
        self.stride = config["stride"]
        self.train_folder = config["train_folder"]
        self.validation_folder = config["validation_folder"]
        self.validation = config["validation"]
        self.batch_size = config["batch_size"]
        self.lr = config["lr"]
        self.epochs = config["epochs"]
        self.augmentation = config["augmentation"]

        self.history = {}
        self.val_history = {}
        self.weights = []
        
        
        self.short = []
        self.long = []   
        
    def __str__(self):
        return "Net instance"
    
        
    def load_training_dataset(self):
        self.weights = []
        short_files = [f for f in listdir(self.train_folder + "/short/") if isfile(join(self.train_folder + "/short/", f))\
                          and f.endswith(".fits")]
        long_files = [f for f in listdir(self.train_folder + "/long/") if isfile(join(self.train_folder + "/long/", f))\
                          and f.endswith(".fits")]
        
        assert len(short_files) == len(long_files), 'Numbers of files in `long` and `short` subfolders should be equal'
        
        assert len(short_files) > 0 and len(long_files) > 0, 'No training data found in {}'.format(self.train_folder)
        
        for i in range(len(short_files)):
            assert(short_files[i] == long_files[i]), 'Corresponding names of short and long files should be equal'
        
        print("Total training images found: {}".format(len(short_files)))
        
        self.short = []
        self.long = []
        
        self.median = []
        self.mad = []
        
        for i in short_files:
            if self.mode == "RGB":
                self.short.append(np.moveaxis(fits.getdata(self.train_folder + "/short/" + i, ext=0), 0, 2))
                self.long.append(np.moveaxis(fits.getdata(self.train_folder + "/long/" + i, ext=0), 0, 2))
                
                     
            else:
                self.short.append(np.moveaxis(np.array([fits.getdata(self.train_folder + "/short/" + i, ext=0)]), 0, 2))
                self.long.append(np.moveaxis(np.array([fits.getdata(self.train_folder + "/long/" + i, ext=0)]), 0, 2))
        
        
        linked_stretch = True
        
        for image in self.short:
            median = []
            mad = []
            
            if linked_stretch:
                median_allcolors = np.median(image[::4,::4,:])
                mad_allcolors = np.median(np.abs(image[::4,::4,:] - median_allcolors))
                
                median = [median_allcolors for i in range(self.input_channels)]
                mad = [mad_allcolors for i in range(self.input_channels)]

            else:
                for c in range(image.shape[-1]):
                    median.append(np.median(image[:,:,c]))
                    mad.append(np.median(np.abs(image[:,:,c] - median[c])))
                
            self.median.append(median)
            self.mad.append(mad)
        
        
        total_pixels = 0
        
        for i in range(len(short_files)):
            assert self.short[i].shape == self.long[i].shape, 'Image sizes are not equal: {}/short/{} and {}/long/{}'\
                                                                      .format(self.train_folder, short_files[i],\
                                                                      self.train_folder, long_files[i])
            
            total_pixels += self.short[i].shape[0] * self.short[i].shape[1]
            self.weights.append(self.short[i].shape[0] * self.short[i].shape[1])
        
        print("Total size of training images: %.2f MP" % (total_pixels / 1e6))
        
        self.iters_per_epoch = total_pixels // (self.window_size * self.window_size) // 2
        
        self.weights = [i / np.sum(self.weights) for i in self.weights]
        
        print("One epoch is set to %d iterations" % self.iters_per_epoch)
        print("Training dataset has been successfully loaded!")
        
        if self.validation:
            self.load_validation_dataset()

        
    def load_validation_dataset(self):
        val_short_files = [f for f in listdir(self.validation_folder + "/short/") if isfile(join(self.validation_folder + "/short/", f))\
                          and f.endswith(".fits")]
        val_long_files = [f for f in listdir(self.validation_folder + "/long/") if isfile(join(self.validation_folder + "/long/", f))\
                          and f.endswith(".fits")]
        
        assert len(val_short_files) == len(val_long_files), 'Numbers of files in `long` and `short` validation subfolders should be equal'
        
        assert len(val_short_files) > 0 and len(val_long_files) > 0, 'No validation data found in {}'.format(self.validation_train_folder)
        
        for i in range(len(val_short_files)):
            assert(val_short_files[i] == val_long_files[i]), 'Corresponding names of short and long validation files should be equal'
        
        print("Total validation images found: {}".format(len(val_short_files)))
        
        self.val_short = []
        self.val_long = []
        
        self.val_median = []
        self.val_mad = []
        
        for i in val_short_files:
            if self.mode == "RGB":
                self.val_short.append(np.moveaxis(fits.getdata(self.validation_folder + "/short/" + i, ext=0), 0, 2))
                self.val_long.append(np.moveaxis(fits.getdata(self.validation_folder + "/long/" + i, ext=0), 0, 2))
                
                     
            else:
                self.val_short.append(np.moveaxis(np.array([fits.getdata(self.validation_folder + "/short/" + i, ext=0)]), 0, 2))
                self.val_long.append(np.moveaxis(np.array([fits.getdata(self.validation_folder + "/long/" + i, ext=0)]), 0, 2))
        
        
        linked_stretch = True
        
        for image in self.val_short:
            median = []
            mad = []
            
            if linked_stretch:
                for c in range(image.shape[-1]):
                    median.append(np.median(image[:,:,:]))
                    mad.append(np.median(np.abs(image[:,:,:] - median[c])))
            else:
                for c in range(image.shape[-1]):
                    median.append(np.median(image[:,:,c]))
                    mad.append(np.median(np.abs(image[:,:,c] - median[c])))
                
            self.val_median.append(median)
            self.val_mad.append(mad)
            
        
        print("Validation dataset has been successfully loaded!")
 

    def load_model(self, weights = None, history = None):
        self.G = self._generator()
        self.D = self._discriminator()
        
        self.gen_optimizer = tf.optimizers.Adam(self.lr)
        self.dis_optimizer = tf.optimizers.Adam(self.lr / 4)
        
        self.D.build(input_shape = (None, self.window_size, self.window_size, self.input_channels))
        self.G.build(input_shape = (None, self.window_size, self.window_size, self.input_channels))
        

        if weights:
            self.G.load_weights(weights + '_G_' + self.mode + '.h5')
            self.D.load_weights(weights + '_D_' + self.mode + '.h5')
        if history:
            with open(history + '_' + self.mode + '.pkl', "rb") as h:
                self.history = pickle.load(h)
                
            with open(history + '_val_' + self.mode + '.pkl', "rb") as h:
                self.val_history = pickle.load(h)
  
    def initialize_model(self):
        self.load_model()
    
    def _ramp(self, x):
        return tf.clip_by_value(x, 0, 1)
    
    def linear_fit(self, o, s, clipping):
        for c in range(o.shape[-1]):
            indx_clipped = o[:,:,c].flatten() < clipping
            coeff = np.polyfit(s[:,:,c].flatten()[indx_clipped], o[:,:,c].flatten()[indx_clipped], 1)
            s[:,:,c] = s[:,:,c]*coeff[0] + coeff[1]
            
    def _augmentator(self, o, s, median, mad):
        
        self.linear_fit(o, s, 0.95)
                   
        # stretch
        sigma = 1.5 + (4.0-1.5)*np.random.rand()
        bg = 0.15 + (0.3-0.15)*np.random.rand()
        
        #sigma = 3.0
        #bg = 0.15
        
        o, s = stretch(o, s, bg, sigma, median, mad)

              
        # flip horizontally
        if np.random.rand() < 0.50:
            o = np.flip(o, axis = 1)
            s = np.flip(s, axis = 1)
        
        # flip vertically
        if np.random.rand() < 0.50:
            o = np.flip(o, axis = 0)
            s = np.flip(s, axis = 0)
        
        # rotate 90, 180 or 270
        if np.random.rand() < 0.75:
            k = int(np.random.rand() * 3 + 1)
            o = np.rot90(o, k, axes = (1, 0))
            s = np.rot90(s, k, axes = (1, 0))
        
        if self.mode == 'RGB':
            
            o_hsv = rgb_to_hsv(o)
            s_hsv = rgb_to_hsv(s)
            
            # tweak hue
            hue = np.random.normal(0,0.2)
            o_hsv[:,:,0] += hue
            s_hsv[:,:,0] += hue
            
            o_hsv[:,:,0] = np.where(o_hsv[:,:,0] < 0, o_hsv[:,:,0] + 1, o_hsv[:,:,0])
            o_hsv[:,:,0] = np.where(o_hsv[:,:,0] > 1, o_hsv[:,:,0] - 1, o_hsv[:,:,0])
            s_hsv[:,:,0] = np.where(s_hsv[:,:,0] < 0, s_hsv[:,:,0] + 1, s_hsv[:,:,0])
            s_hsv[:,:,0] = np.where(s_hsv[:,:,0] > 1, s_hsv[:,:,0] - 1, s_hsv[:,:,0])
        
            # tweak saturation
            sat = np.random.normal(1.25,0.25)
            o_hsv[:,:,1] *= sat
            s_hsv[:,:,1] *= sat           
            
            # tweak value
            val = np.random.normal(0,0.1)
            o_hsv[:,:,2] += val
            s_hsv[:,:,2] += val
            
            o_hsv = np.clip(o_hsv,0,1)
            s_hsv = np.clip(s_hsv,0,1)
            
            o[:,:,:] = hsv_to_rgb(o_hsv)
            s[:,:,:] = hsv_to_rgb(s_hsv)
                    
        else:
            # tweak brightness
            if np.random.rand() < 0.70:
                m = np.min((o, s))
                offset = np.random.rand() * 0.25 - np.random.rand() * m
                o[:, :] = o[:, :] + offset * (1.0 - o[:, :])
                s[:, :] = s[:, :] + offset * (1.0 - s[:, :])
            
        o = np.clip(o, 0.0, 1.0)
        s = np.clip(s, 0.0, 1.0)
        
        return o, s

            
    def _get_sample(self, r, h, w, type:str):
        assert type in ['short', 'long']
        if type == 'short':
            return np.copy(self.short[r][h:h+self.window_size, w:w+self.window_size])
        else:
            return np.copy(self.long[r][h:h+self.window_size, w:w+self.window_size])
        
    def generate_input(self, iterations = 1):
        for _ in range(iterations):
            o = np.zeros((self.batch_size, self.window_size, self.window_size, self.input_channels), dtype = np.float32)
            s = np.zeros((self.batch_size, self.window_size, self.window_size, self.input_channels), dtype = np.float32)
                
            for i in range(self.batch_size):
                if self.augmentation:
                    r = int(np.random.choice(range(len(self.short)), 1, p = self.weights))
                    h = np.random.randint(self.short[r].shape[0] - self.window_size)
                    w = np.random.randint(self.short[r].shape[1] - self.window_size)
                    o[i], s[i] = self._augmentator(self._get_sample(r, h, w, type = 'short'),\
                                                   self._get_sample(r, h, w, type = 'long'), self.median[r], self.mad[r])
                else:
                    r = int(np.random.choice(range(len(self.short)), 1, p = self.weights))
                    h = np.random.randint(self.short[r].shape[0] - self.window_size)
                    w = np.random.randint(self.short[r].shape[1] - self.window_size)
                    o[i] = self._get_sample(r, h, w, type = 'short')
                    s[i] = self._get_sample(r, h, w, type = 'long')
        return o, s
        
        
    def train(self, plot_progress = False, plot_interval = 50, save_backups = False, warm_up = False):
        assert self.short != [], 'Training dataset was not loaded, use load_training_dataset() first'
        
        for e in range(self.epochs):
            for i in range(self.iters_per_epoch):
                
                if self.validation and i % 1000 == 0 and i != 0:
                    self.validate()
                
                x, y = self.generate_input()

                x = x * 2 - 1
                y = y * 2 - 1
                
                if warm_up: y = x
                
                if i % plot_interval == 0 and plot_progress:
                    plt.close()
                    fig, ax = plt.subplots(1, 4, sharex = True, figsize=(16.5, 16.5))
                    if self.mode == 'RGB':
                        ax[0].imshow((x[0] + 1) / 2)
                        ax[0].set_title('short')
                        ax[1].imshow((self.G(x)[0] + 1) / 2)
                        ax[1].set_title('output')
                        ax[2].imshow((y[0] + 1) / 2)
                        ax[2].set_title('long')
                        
                        ax[3].imshow(10 * np.abs((y[0] + 1) / 2 - (self.G(x)[0] + 1) / 2))
                        ax[3].set_title('Difference x10')

                    else:
                        ax[0].imshow((x[0, :, :, 0] + 1) / 2, cmap='gray', vmin = 0, vmax = 1)
                        ax[0].set_title('short')
                        ax[1].imshow((self.G(x)[0, :, :, 0] + 1) / 2, cmap='gray', vmin = 0, vmax = 1)
                        ax[1].set_title('long')
                        ax[2].imshow((y[0, :, :, 0] + 1) / 2, cmap='gray', vmin = 0, vmax = 1)
                        ax[2].set_title('Target')
                    
                    display.clear_output(wait = True)
                    display.display(plt.gcf())
                
                if i > 0:
                    print("\rEpoch: %d. Iteration %d / %d Loss %f L1 Loss %f   " % (e, i, self.iters_per_epoch, np.mean(self.history['total'][-500:]), np.mean(self.history['gen_L1'][-500:])), end = '')
                    #print("\rEpoch: %d. Iteration %d / %d L1 Loss %f   " % (e, i, self.iters_per_epoch, self.history['gen_L1'][-1]), end = '')
                else:
                    print("\rEpoch: %d. Iteration %d / %d " % (e, i, self.iters_per_epoch), end = '')
                
                
                with tf.GradientTape() as gen_tape, tf.GradientTape() as dis_tape:
                    gen_output = self.G(x)
                    
                    p1_real, p2_real, p3_real, p4_real, p5_real, p6_real, p7_real, p8_real, predict_real = self.D(y)
                    p1_fake, p2_fake, p3_fake, p4_fake, p5_fake, p6_fake, p7_fake, p8_fake, predict_fake = self.D(gen_output)
                    
                    d = {}
                    
                    dis_loss = tf.reduce_mean(-(tf.math.log(predict_real + 1E-8) + tf.math.log(1 - predict_fake + 1E-8)))
                    d['dis_loss'] = dis_loss
                    
                    gen_loss_GAN = tf.reduce_mean(-tf.math.log(predict_fake + 1E-8))
                    d['gen_loss_GAN'] = gen_loss_GAN
                    
                    gen_p1 = tf.reduce_mean(tf.abs(p1_fake - p1_real))
                    d['gen_p1'] = gen_p1
                    
                    gen_p2 = tf.reduce_mean(tf.abs(p2_fake - p2_real))
                    d['gen_p2'] = gen_p2
                    
                    gen_p3 = tf.reduce_mean(tf.abs(p3_fake - p3_real))
                    d['gen_p3'] = gen_p3
                    
                    gen_p4 = tf.reduce_mean(tf.abs(p4_fake - p4_real))
                    d['gen_p4'] = gen_p4
                    
                    gen_p5 = tf.reduce_mean(tf.abs(p5_fake - p5_real))
                    d['gen_p5'] = gen_p5
                    
                    gen_p6 = tf.reduce_mean(tf.abs(p6_fake - p6_real))
                    d['gen_p6'] = gen_p6
                    
                    gen_p7 = tf.reduce_mean(tf.abs(p7_fake - p7_real))
                    d['gen_p7'] = gen_p7
                    
                    gen_p8 = tf.reduce_mean(tf.abs(p8_fake - p8_real))
                    d['gen_p8'] = gen_p8
                    
                    gen_L1 = tf.reduce_mean(tf.abs(y - gen_output))
                    d['gen_L1'] = gen_L1 * 100
                    
                    gen_loss = gen_loss_GAN * 0.1 + gen_p1 * 0.1 + gen_p2 * 10 + gen_p3 * 10 + gen_p4 * 10 + gen_p5 * 10 + gen_p6 * 10 + gen_p7 * 10 + gen_p8 * 10 + gen_L1 * 100
                    #gen_loss = gen_L1 * 100
                    d['total'] = gen_loss
                    
                    for k in d:
                        if k in self.history.keys():
                            self.history[k].append(d[k])
                        else:
                            self.history[k] = [d[k]]
                    
                    gen_grads = gen_tape.gradient(gen_loss, self.G.trainable_variables)
                    self.gen_optimizer.apply_gradients(zip(gen_grads, self.G.trainable_variables))
                    
                    dis_grads = dis_tape.gradient(dis_loss, self.D.trainable_variables)
                    self.dis_optimizer.apply_gradients(zip(dis_grads, self.D.trainable_variables))
                    
                    
            if save_backups:
                if e % 2 == 0:
                    self.G.save_weights("./Net_backup_G_even.h5")
                    self.D.save_weights("./Net_backup_D_even.h5")
                else:
                    self.G.save_weights("./Net_backup_G_odd.h5")
                    self.D.save_weights("./Net_backup_D_odd.h5")
            
            if plot_progress: plt.close()

    
    def validate(self):
        
        print("Start validation")
        
        val_metrics = {"L1_loss": 0.0, "dis_loss": 0.0, "psnr": 0.0, "SSIM": 0.0}

        
        for i in range(len(self.val_short)):
            h, w, _ = self.val_short[i].shape
            
            ith = h // self.window_size
            itw = w // self.window_size
            
            num_iterations = 0
            
            for x in range(ith):
                for y in range(itw):
                    num_iterations += 1
                    
                    # Slice
                    short = self.val_short[i][x*self.window_size:(x+1)*self.window_size,y*self.window_size:(y+1)*self.window_size]
                    long = self.val_long[i][x*self.window_size:(x+1)*self.window_size,y*self.window_size:(y+1)*self.window_size]
                    
                    self.linear_fit(short, long, 0.95)
                    
                    # Stretch
                    bg = 0.2
                    sigma = 3.0
                    short, long = stretch(short, long, bg, sigma, self.val_median[i], self.val_mad[i])
                    
                    
                    output = self.G(np.expand_dims(short * 2 - 1, axis = 0))[0]
                    output = (output + 1) / 2
                    
                    # Calculate metrics
                    val_metrics["L1_loss"] += tf.reduce_mean(tf.abs(long - output)) * 2 * 100
                    
                    p1_real, p2_real, p3_real, p4_real, p5_real, p6_real, p7_real, p8_real, predict_real = self.D(np.expand_dims(long*2 - 1, axis = 0))
                    p1_fake, p2_fake, p3_fake, p4_fake, p5_fake, p6_fake, p7_fake, p8_fake, predict_fake = self.D(np.expand_dims(output*2 - 1, axis = 0))
                    
                    val_metrics["dis_loss"] += tf.reduce_mean(-(tf.math.log(predict_real + 1E-8) + tf.math.log(1 - predict_fake + 1E-8)))
                    
                    val_metrics["psnr"] += tf.image.psnr(long, output, max_val = 1.0)

                    val_metrics["SSIM"] += tf.image.ssim(long, output, max_val = 1.0)
                    
                    
        
        for metric in val_metrics:
            if metric in self.val_history:
                self.val_history[metric].append(val_metrics[metric] / num_iterations)
            else:
                self.val_history[metric] = [val_metrics[metric] / num_iterations]
                
            print(metric + ": " + str(val_metrics[metric] / num_iterations))
        
        
        print("Finished validation")
                    
                           
    
    def plot_history(self, last = None):
        assert self.history != {}, 'Empty training history, nothing to plot'
        fig, ax = plt.subplots(4, 3, sharex = True, figsize=(16, 14))
        
        keys = list(self.history.keys())
        
        keys = [k for k in keys if k != '']
        
        for i in range(4):
            for j in range(3):
                if last: ax[i][j].plot(self.history[keys[j+3*i]][-last:])
                else: ax[i][j].plot(self.history[keys[j+3*i]])
                ax[i][j].set_title(keys[j+3*i])
                
        
        if self.validation:
        
            fig, ax = plt.subplots(1, 4, sharex = True, figsize=(16, 14))
            
            keys = list(self.val_history.keys())
            
            keys = [k for k in keys if k != '']
            
            for i in range(4):
                if last: ax[i].plot(self.val_history[keys[i]][-last:])
                else: ax[i].plot(self.val_history[keys[i]])
                ax[i].set_title(keys[i])
                
    def save_model(self, weights_filename, history_filename = None):

        self.G.save_weights(weights_filename + '_G_' + self.mode + '.h5')
        self.D.save_weights(weights_filename + '_D_' + self.mode + '.h5')
        if history_filename:
            with open(history_filename + '_' + self.mode + '.pkl', 'wb') as f:
                pickle.dump(self.history, f)
                
            with open(history_filename + '_val_' + self.mode + '.pkl', 'wb') as f:
                pickle.dump(self.val_history, f)

    def save(self, weights_filename, history_filename = None):
        self.G.save(weights_filename)
      
    def transform(self, in_name, out_name):
        print("Started")
        if self.mode == "RGB":
            data = np.moveaxis(fits.getdata(in_name, ext=0), 0, 2)
        else:
            data = np.moveaxis(np.array([fits.getdata(in_name, ext=0)]), 0, 2)
    
        image = data
        H, W, _ = image.shape
        
        offset = int((self.window_size - self.stride) / 2)
        
        h, w, _ = image.shape
        
        ith = int(h / self.stride) + 1
        itw = int(w / self.stride) + 1
        
        dh = ith * self.stride - h
        dw = itw * self.stride - w
        
        image = np.concatenate((image, image[(h - dh) :, :, :]), axis = 0)
        image = np.concatenate((image, image[:, (w - dw) :, :]), axis = 1)
        
        h, w, _ = image.shape
        image = np.concatenate((image, image[(h - offset) :, :, :]), axis = 0)
        image = np.concatenate((image[: offset, :, :], image), axis = 0)
        image = np.concatenate((image, image[:, (w - offset) :, :]), axis = 1)
        image = np.concatenate((image[:, : offset, :], image), axis = 1)
        
        image = image * 2 - 1
        
        output = copy.deepcopy(image)
        
        for i in range(ith):
            print(str(i) + " of " + str(ith))
            for j in range(itw):
                x = self.stride * i
                y = self.stride * j
                
                tile = np.expand_dims(image[x:x+self.window_size, y:y+self.window_size, :], axis = 0)
                tile = np.array(self.G(tile)[0])
                #self.linear_fit(image[x:x+self.window_size, y:y+self.window_size, :], tile, 0.95)
                tile = (tile + 1) / 2
                tile = tile[offset:offset+self.stride, offset:offset+self.stride, :]
                output[x+offset:self.stride*(i+1)+offset, y+offset:self.stride*(j+1)+offset, :] = tile
        
        output = np.clip(output, 0, 1)
        output = output[offset:H+offset,offset:W+offset,:]
        
        if self.mode == "RGB":
            self.save_fits(np.moveaxis(output,2,0),out_name,"./")
        else:
            self.save_fits(np.moveaxis(output,2,0)[0],out_name,"./")
            
        print("Finished")
            
    def save_fits(self, image, name, path):
         hdu = fits.PrimaryHDU(image)
         hdul = fits.HDUList([hdu])
         hdul.writeto(path + name + '.fits')       

    def _generator(self):
        #return pridnet(self.window_size,self.input_channels)
        #return unet(self.window_size,self.input_channels)
        return ridnet(self.window_size,self.input_channels)
        
    def _discriminator(self):
        layers = []
        filters = [32, 64, 64, 128, 128, 256, 256, 256, 8]
        #filters = [int(1/2*filter) for filter in filters]
        
        input = L.Input(shape=(self.window_size, self.window_size, self.input_channels), name = "dis_input_image")
        
        # layer 1
        convolved = L.Conv2D(filters[0], kernel_size = 3, strides = (1, 1), padding="same")(input)
        rectified = L.LeakyReLU(alpha = 0.2)(convolved)
        layers.append(rectified)
            
        # layer 2
        convolved = L.Conv2D(filters[1], kernel_size = 3, strides = (2, 2), padding="valid")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 3
        convolved = L.Conv2D(filters[2], kernel_size = 3, strides = (1, 1), padding="same")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 4
        convolved = L.Conv2D(filters[3], kernel_size = 3, strides = (2, 2), padding="valid")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 5
        convolved = L.Conv2D(filters[4], kernel_size = 3, strides = (1, 1), padding="same")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 6
        convolved = L.Conv2D(filters[5], kernel_size = 3, strides = (2, 2), padding="valid")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 7
        convolved = L.Conv2D(filters[6], kernel_size = 3, strides = (1, 1), padding="same")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 8
        convolved = L.Conv2D(filters[7], kernel_size = 3, strides = (2, 2), padding="valid")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 9
        convolved = L.Conv2D(filters[8], kernel_size = 3, strides = (2, 2), padding="valid")(layers[-1])
        normalized = L.BatchNormalization()(convolved, training = True)
        rectified = L.LeakyReLU(alpha = 0.2)(normalized)
        layers.append(rectified)
            
        # layer 10
        dense = L.Dense(1)(layers[-1])
        sigmoid = tf.nn.sigmoid(dense)
        layers.append(sigmoid)
        
        output = [layers[0], layers[1], layers[2], layers[3], layers[4], layers[5], layers[6], layers[7], layers[-1]]
            
        return K.Model(inputs = input, outputs = output, name = "discriminator")
    

config = load_config("./config/my_config.json")

Net = Net(config)
Net.load_training_dataset()

#Net.load_model('./weights_ridnet_dis/weights')
Net.load_model(config["weights"], config["history"])


Net.train(plot_progress = True, plot_interval = 50, save_backups=False, warm_up = False)
Net.save_model('./weights', './history')

Net.plot_history()
#Net.transform("./noisy.fits","denoised")
