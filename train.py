from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import random
import time

import numpy as np
import tensorflow as tf
from tqdm import trange

from model import stacked_capsule_autoencoders
from utilities import get_dataset, block_warnings, ModelCollector, to_float32


class SCAE(ModelCollector):
	def __init__(
			self,
			input_size,
			template_size=11,
			n_part_caps=16,
			n_part_caps_dims=6,
			n_part_special_features=16,
			part_encoder_noise_scale=0.,
			n_channels=1,
			colorize_templates=False,
			use_alpha_channel=False,
			template_nonlin='relu1',
			color_nonlin='relu1',
			n_obj_caps=10,
			n_obj_caps_params=32,
			obj_decoder_noise_type=None,
			obj_decoder_noise_scale=0.,
			num_classes=10,
			stop_gradient=True,
			prior_within_example_sparsity_weight=1.,
			prior_between_example_sparsity_weight=1.,
			posterior_within_example_sparsity_weight=10.,
			posterior_between_example_sparsity_weight=10.,
			is_training=True,
			learning_rate=1e-4,
			use_lr_schedule=True,
			scope='SCAE',
			snapshot=None
	):
		if input_size is None:
			input_size = [20, 224, 224, 3]

		graph = tf.Graph()

		with graph.as_default():
			self.sess = tf.Session(graph=graph, config=tf.ConfigProto(gpu_options=tf.GPUOptions(allow_growth=True)))

			self.batch_input = tf.placeholder(tf.float32, input_size)
			self.model = stacked_capsule_autoencoders(input_size[1],  # Assume width equals height
			                                          template_size,
			                                          n_part_caps,
			                                          n_part_caps_dims,
			                                          n_part_special_features,
			                                          part_encoder_noise_scale,
			                                          n_channels,
			                                          colorize_templates,
			                                          use_alpha_channel,
			                                          template_nonlin,
			                                          color_nonlin,
			                                          n_obj_caps,
			                                          n_obj_caps_params,
			                                          obj_decoder_noise_type,
			                                          obj_decoder_noise_scale,
			                                          num_classes,
			                                          stop_gradient,
			                                          prior_within_example_sparsity_weight,
			                                          prior_between_example_sparsity_weight,
			                                          posterior_within_example_sparsity_weight,
			                                          posterior_between_example_sparsity_weight,
			                                          scope)

			if is_training:
				self.labels = tf.placeholder(tf.int64, [input_size[0]])
				data = {'image': self.batch_input, 'label': self.labels}
				self.res = self.model(data)

				self.loss = self.model._loss(data, self.res)

				if use_lr_schedule:
					global_step = tf.train.get_or_create_global_step()
					learning_rate = tf.train.exponential_decay(
						global_step=global_step,
						learning_rate=learning_rate,
						decay_steps=1e4,
						decay_rate=.96
					)
					global_step.initializer.run(session=self.sess)

				eps = 1e-2 / float(input_size[0]) ** 2
				optimizer = tf.train.RMSPropOptimizer(learning_rate, momentum=.9, epsilon=eps)

				self.train_step = optimizer.minimize(self.loss, var_list=tf.trainable_variables(scope=scope))
				self.sess.run(tf.initialize_variables(var_list=optimizer.variables()))
			else:
				data = {'image': self.batch_input}
				self.res = self.model(data)

			self.saver = tf.train.Saver(var_list=tf.trainable_variables(scope=scope))

			if snapshot:
				print('Restoring from snapshot: {}'.format(snapshot))
				self.saver.restore(self.sess, snapshot)
			else:
				self.sess.run(tf.initialize_variables(var_list=tf.trainable_variables(scope=scope)))

			# Freeze graph
			self.sess.graph.finalize()

	def run(self, images, to_collect):
		return self.sess.run(to_collect, feed_dict={self.batch_input: images})

	def __call__(self, images):
		return self.sess.run(self.res.prior_cls_logits, feed_dict={self.batch_input: images})


if __name__ == '__main__':
	block_warnings()

	dataset = 'mnist'
	batch_size = 100
	canvas_size = 28
	max_train_steps = 300
	learning_rate = 3e-5
	n_part_caps = 40
	n_obj_caps = 32
	n_channels = 1
	colorize_templates = True
	use_alpha_channel = True
	prior_within_example_sparsity_weight = 2.
	prior_between_example_sparsity_weight = 0.35
	posterior_within_example_sparsity_weight = 0.7
	posterior_between_example_sparsity_weight = 0.2
	template_nonlin = 'sigmoid'
	color_nonlin = 'sigmoid'
	part_encoder_noise_scale = 4.0
	obj_decoder_noise_type = 'uniform'
	obj_decoder_noise_scale = 4.0
	snapshot = './checkpoints/{}/model.ckpt'.format(dataset)

	path = snapshot[:snapshot.rindex('/')]
	if not os.path.exists(path):
		os.makedirs(path)

	model = SCAE(
		input_size=[batch_size, canvas_size, canvas_size, n_channels],
		num_classes=10,
		n_part_caps=n_part_caps,
		n_obj_caps=n_obj_caps,
		n_channels=n_channels,
		colorize_templates=colorize_templates,
		use_alpha_channel=use_alpha_channel,
		prior_within_example_sparsity_weight=prior_within_example_sparsity_weight,
		prior_between_example_sparsity_weight=prior_between_example_sparsity_weight,
		posterior_within_example_sparsity_weight=posterior_within_example_sparsity_weight,
		posterior_between_example_sparsity_weight=posterior_between_example_sparsity_weight,
		template_nonlin=template_nonlin,
		color_nonlin=color_nonlin,
		part_encoder_noise_scale=part_encoder_noise_scale,
		obj_decoder_noise_type=obj_decoder_noise_type,
		obj_decoder_noise_scale=obj_decoder_noise_scale,
		is_training=True,
		learning_rate=learning_rate,
		scope='SCAE',
		# use_lr_schedule=False,
		# snapshot=snapshot
	)

	trainset = get_dataset(dataset, 'train', shape=[canvas_size, canvas_size], file_path='./datasets')
	testset = get_dataset(dataset, 'test', shape=[canvas_size, canvas_size], file_path='./datasets')

	len_trainset = len(trainset['image'])
	len_testset = len(testset['image'])

	train_batches = np.int(np.ceil(np.float(len_trainset) / np.float(batch_size)))
	test_batches = np.int(np.ceil(np.float(len_testset) / np.float(batch_size)))

	random.seed(time.time())
	shuffle_indices = list(range(len_trainset))

	for epoch in range(max_train_steps):
		print('\n[Epoch {}/{}]'.format(epoch + 1, max_train_steps))

		random.shuffle(shuffle_indices)

		for i_batch in trange(train_batches, desc='Training'):
			i_start = (i_batch * batch_size)
			i_end = min((i_batch + 1) * batch_size, len_trainset)
			indices = shuffle_indices[i_start:i_end]
			images = to_float32(trainset['image'][indices])
			labels = trainset['label'][indices]
			model.sess.run(model.train_step, feed_dict={model.batch_input: images, model.labels: labels})

		test_loss = 0.
		test_acc_prior = 0.
		test_acc_posterior = 0.
		for i_batch in trange(test_batches, desc='Testing'):
			i_start = (i_batch * batch_size)
			i_end = min((i_batch + 1) * batch_size, len_testset)
			images = to_float32(testset['image'][i_start:i_end])
			labels = testset['label'][i_start:i_end]
			test_pred_prior, test_pred_posterior, _test_loss = model.sess.run(
				[model.res.prior_cls_pred, model.res.posterior_cls_pred, model.loss],
				feed_dict={model.batch_input: images, model.labels: labels})
			test_loss += _test_loss
			test_acc_prior += (test_pred_prior == labels).sum()
			test_acc_posterior += (test_pred_posterior == labels).sum()
			assert not np.isnan(test_loss)
		print('loss: {:.6f}  prior acc: {:.6f}  posterior acc: {:.6f}'.format(
			test_loss / len_testset,
			test_acc_prior / len_testset,
			test_acc_posterior / len_testset
		))

		print('Saving model...')
		model.saver.save(model.sess, snapshot)
