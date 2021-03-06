import tensorflow as tf
from custom_layers_func import MiniBatchStdev, WeightedSum, PixelNorm

# wasserstein loss
def wasserstein_loss(y_true, y_pred):
    return tf.keras.backend.mean(y_pred*y_true)

# adds a generator block
def add_gen_block(old_model):
    # weight initializaiton
    init = tf.keras.initializers.RandomNormal(stddev=0.02)

    # weight constraint
    const = tf.keras.constraints.max_norm(1.0)

    end_block = old_model.layers[-2].output

    # upsample
    upsamp = tf.keras.layers.UpSampling2D()(end_block)

    g = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(upsamp)
    g = PixelNorm()(g)
    g = tf.keras.layers.LeakyReLU(alpha=0.2)(g)
    
    g = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(g)
    g = PixelNorm()(g)
    g = tf.keras.layers.LeakyReLU(alpha=0.2)(g)

    # add new output layer
    out_img = tf.keras.layers.Conv2D(3, (1,1), padding="same", kernel_initializer=init, kernel_constraint=const)(g)

    #define model
    m1 = tf.keras.models.Model(old_model.input, out_img)

    # get output layer from old model
    old_out = old_model.layers[-1]

    # connect the old output layer to upsampling
    out_img2 = old_out(upsamp)

    # define new output image as the weighted sum of old and new models
    merged = WeightedSum()([out_img2, out_img])

    # define model
    m2 = tf.keras.models.Model(old_model.input, merged)

    return [m1, m2]


# adds a discriminator block
def add_disc_block(old_model, n_input_layers=3):
    # weights initialization
    init = tf.keras.initializers.RandomNormal(stddev=0.02)

    # constraints
    const = tf.keras.constraints.max_norm(1.0)

    # shape of existing model
    in_shape = list(old_model.input.shape)

    input_shape = (in_shape[-2].value*2, in_shape[-2].value*2, in_shape[-1].value)

    in_image = tf.keras.layers.Input(shape=input_shape)

    # new input layer
    d = tf.keras.layers.Conv2D(128, (1,1), padding="same", kernel_intializer=init, kernel_constraint=const)(in_image)
    d = tf.keras.layers.LeakyReLU(alpha=0.2)(d)

    d = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(d)
    d = tf.keras.layers.LeakyRelu(alpha=0.2)(d)

    d = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(d)
    d = tf.keras.layers.LeakyRelu(alpha=0.2)(d)

    d = tf.keras.layers.AveragePooling2D()(d)

    new_block = d

    # skip the input, 1X1 and activation for old model
    for i in range(n_input_layers, len(old_model.layers)):
        d = old_model.layers[i](d)
    
    # define straight-through model
    m1 = tf.keras.models.Model(in_image, d)

    # compile model
    m1.compile(loss=wasserstein_loss, optimizer=tf.keras.optimizers.Adam(learning_rate=0.001, beta_1=0, beta_2=0.99, epsilon=10e-8))

    # downsample the new larger image
    downsample = tf.keras.layes.AveragePooling2D()(in_image)

    # connect old input processing to downsampled new input
    old_block = old_model.layers[1](downsample)
    old_block = old_model.layers[2](old_block)

    # fade-in output of old model -> input layer with new input
    d = WeightedSum()([old_block, new_block])

    # skip the input, 1X1 and activation for the old model
    for i in range(n_input_layers, len(old_model.layers)):
        d = old_model.layers[i](d)
    
    # define straight-through model
    m2 = tf.keras.models.Model(in_image, d)

    # compile the model
    m2.compile(loss=wasserstein_loss, optimizer=tf.keras.optimizers.Adam(learning_rate=0.001, beta_1=0, beta_2=0.99, epsilon=10e-8))

    return [m1, m2]

# define discriminator model
# input image start with 4X4 RGB
# add layers until it reaches required resolution
def discriminator(n_blocks, input_shape=(4,4,3)):
    # weight initialization
    init = tf.keras.initializers.RandomNormal(stddev=0.02)

    # weight constraint
    const = tf.keras.constraints.max_norm(1.0)

    # initializing empty list for storing models
    model_list = list()

    # starting model input
    in_image = tf.keras.layers.Input(input_shape)

    # conv 1X1
    d = tf.keras.layers.Conv2D(128, (1,1), padding="same", kernel_initializer=init, kernel_constraint=const)(in_image)
    d = tf.keras.layers.LeakyReLU(alpha=0.2)(d)

    # conv 3X3
    d = MiniBatchStdev()(d)
    d = tf.keras.layers.Conv2D(128, (1,1), padding="same", kernel_initializer=init, kernel_constraint=const)(d)
    d = tf.keras.layers.LeakyReLU(alpha=0.2)(d)

    # conv 4X4
    d = tf.keras.layers.Conv2D(128, (4,4), padding="same", kernel_initializer=init, kernel_constraint=const)(d)
    d = tf.keras.layers.LeakyReLU(alpha=0.2)(d)

    # dense output layer
    d = tf.keras.layers.Flatten()(d)
    out_class = tf.keras.layers.Dense(1)(d)

    # define model
    model = tf.keras.models.Model(in_image, out_class)

    # compile the model
    model.compile(loss=wasserstein_loss, optimizer=tf.keras.optimizers.Adam(learning_rate=0.001, beta_1=0, beta_2=0.99, epsilon=10e-8))

    # store model
    model_list.append([model, model])

    # creating submodels
    for i in range(0, n_blocks-1):
        # get model without the fade-on
        old_model = model_list[i][0]
        models = add_disc_block(old_model)

        # store model
        model_list.append(models)
    
    return model_list


def generator(latent_dim, num_blocks, in_dim=4):
    # weight initialization
    init = tf.keras.initializers.RandomNormal(stddev=0.02)

    # weight constraint
    const = tf.keras.constraints.max_norm(1.0)
    model_list = list()

    # base model latent input
    in_latent = tf.keras.layers.Input(shape=(latent_dim,))

    # linear scale upto activation maps
    g = tf.keras.layers.Dense(128*in_dim*in_dim, kernel_initializer=init, kernel_constraint=const)(in_latent)
    g = tf.keras.layers.Reshape((in_dim, in_dim, 128))(g)

    # conv 4X4(input)
    g = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(g)
    g = PixelNorm()(g)
    g = tf.keras.layers.LeakyReLU(alpha=0.2)(g)

    # conv 3X3
    g = tf.keras.layers.Conv2D(128, (3,3), padding="same", kernel_initializer=init, kernel_constraint=const)(g)
    g = PixelNorm()(g)
    g = tf.keras.layers.LeakyReLU(alpha=0.2)(g)

    # conv 1X1(output)
    out_img = tf.keras.layers.Conv2D(3, (1,1), padding="same", kernel_initializer=init, kernel_constraint=const)(g)

    # define model
    model = tf.keras.models.Model(in_latent, out_img)

    # store model
    model_list.append([model, model])

    # create submodels
    for i in range(0, num_blocks):
        # get prior model without fade-on
        old_model = model_list[i][0]

        # create new model for next resolution
        models = add_gen_block(old_model)

        # store model
        model_list.append(models)
    return model_list